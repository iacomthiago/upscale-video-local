"""Janela do aplicativo de upscale. Abra pelo Iniciar.bat (ou: python app.py)."""
from __future__ import annotations

import os
import queue
import shutil
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import atualizar
import tema
import upscaler
from comparar import Comparador
from tema import px
from upscaler import Cancelado, ErroUpscale, Progresso

EXTENSOES = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
RESOLUCOES = [(720, "720p  HD"), (1080, "1080p  Full HD"), (1440, "1440p  2K")]
SEGUNDOS_TESTE = 3
ASSINATURA = "@iacomthiago"
MINIATURA = (96, 54)


def _duracao(segundos: float) -> str:
    return f"{segundos:.1f} s".replace(".", ",") if segundos < 60 else upscaler.formatar_tempo(segundos)


class Linha:
    """Um video da lista: miniatura, dados e botoes."""

    def __init__(self, app: "App", caminho: Path):
        self.app = app
        self.caminho = caminho
        self.info: Optional[upscaler.InfoVideo] = None
        self.versoes: list[tuple[str, Path, Optional[str]]] = []
        self.foto: Optional[tk.PhotoImage] = None

        self.quadro = tk.Frame(app.lista.dentro, bg=tema.PAINEL)
        self.quadro.pack(fill="x")
        corpo = tk.Frame(self.quadro, bg=tema.PAINEL, padx=px(12), pady=px(10))
        corpo.pack(fill="x")
        tk.Frame(self.quadro, bg=tema.BORDA, height=1).pack(fill="x")

        moldura = tk.Frame(corpo, bg=tema.PAINEL2, width=px(MINIATURA[0]), height=px(MINIATURA[1]))
        moldura.pack(side="left")
        moldura.pack_propagate(False)
        self.miniatura = tk.Label(moldura, bg=tema.PAINEL2, bd=0)
        self.miniatura.pack(expand=True)

        self.b_remover = tema.Botao(corpo, "✕", lambda: app.remover(self), "discreto", padx=px(8), pady=px(4))
        self.b_remover.pack(side="right")
        self.b_comparar = tema.Botao(corpo, "Antes e depois", lambda: app.abrir_comparador(self),
                                     tamanho=9, pady=px(4))
        self.b_testar = tema.Botao(corpo, "Testar qualidades", lambda: app.testar_qualidades(self),
                                   tamanho=9, pady=px(4))
        self.b_testar.pack(side="right", padx=px(6))

        textos = tk.Frame(corpo, bg=tema.PAINEL)
        textos.pack(side="left", fill="x", expand=True, padx=px(12))
        self.nome = tema.rotulo(textos, caminho.name, 10, tema.TEXTO, "bold", anchor="w")
        self.nome.pack(fill="x")
        self.dados = tema.rotulo(textos, "Lendo o vídeo...", 9, tema.SUAVE, anchor="w")
        self.dados.pack(fill="x")
        self.estado = tema.rotulo(textos, "", 9, tema.SUAVE, anchor="w")
        self.estado.pack(fill="x")

    def descrever(self, lado: int) -> None:
        if not self.info:
            return
        i = self.info
        w, h = upscaler.calcular_saida(i.largura, i.altura, lado)
        self.dados.configure(text=f"{i.largura}×{i.altura}  ·  {_duracao(i.duracao)}  →  {w}×{h}")

    def marcar(self, texto: str, cor: str = tema.SUAVE) -> None:
        self.estado.configure(text=texto, fg=cor)

    def guardar_versao(self, nome: str, caminho: Path, modo: Optional[str]) -> None:
        self.versoes = [v for v in self.versoes if v[0] != nome] + [(nome, caminho, modo)]
        if not self.b_comparar.winfo_ismapped():
            self.b_comparar.pack(side="right", before=self.b_testar, padx=(0, px(6)))

    def ligar(self, sim: bool) -> None:
        for b in (self.b_remover, self.b_testar):
            b.ligar(sim)


class CartaoModo(tk.Frame):
    """Cartao clicavel de um modo de qualidade."""

    def __init__(self, mestre, modo: str, ao_escolher):
        super().__init__(mestre, bg=tema.PAINEL, highlightthickness=px(2), padx=px(14), pady=px(12),
                         cursor="hand2")
        self.modo = modo
        self.ao_escolher = ao_escolher
        self.ativo = True
        self.titulo = tema.rotulo(self, upscaler.NOMES_MODOS[modo], 11, tema.TEXTO, "bold", anchor="w")
        self.titulo.pack(fill="x")
        self.resumo = tema.rotulo(self, upscaler.RESUMO_MODOS[modo], 9, tema.SUAVE, anchor="nw",
                                  justify="left", wraplength=px(168), height=2)
        self.resumo.pack(fill="x", pady=(px(2), px(8)))
        self.tempo = tema.rotulo(self, "", 9, tema.OK, anchor="w")
        self.tempo.pack(fill="x")
        for w in (self, self.titulo, self.resumo, self.tempo):
            w.bind("<Button-1>", lambda e: self.ativo and self.ao_escolher(self.modo))

    def pintar(self, escolhido: bool) -> None:
        fundo = tema.PAINEL2 if escolhido else tema.PAINEL
        borda = (tema.DESTAQUE if self.ativo else tema.APAGADO) if escolhido else tema.BORDA
        self.configure(bg=fundo, highlightbackground=borda, highlightcolor=borda,
                       cursor="hand2" if self.ativo else "arrow")
        for w in (self.titulo, self.resumo, self.tempo):
            w.configure(bg=fundo)


class App(tk.Tk):
    def __init__(self, arquivos: list[str]):
        super().__init__()
        self.title(f"Upscale de Vídeo — por {ASSINATURA}")
        tema.preparar(self)
        self.icones = tema.aplicar_icone(self, upscaler.RAIZ / "icone")
        altura = min(px(880), self.winfo_screenheight() - px(100))
        self.geometry(f"{px(940)}x{altura}")
        self.minsize(px(900), px(720))

        self.fila: "queue.Queue[tuple]" = queue.Queue()
        self.cancelar = threading.Event()
        self.trabalhando = False
        self.linhas: list[Linha] = []
        self.comparadores: dict[Path, Comparador] = {}
        self.pasta_saida: Optional[Path] = None
        self.ultima_saida: Optional[Path] = None
        self.pasta_temp: Optional[Path] = None
        self.contador = 0

        self.modo = "rapido"
        self.teste = tk.BooleanVar(value=False)
        self.manter_cores = tk.BooleanVar(value=True)

        self._montar()
        for a in arquivos:
            self._adicionar(Path(a))
        self._atualizar_lista()
        self.protocol("WM_DELETE_WINDOW", self._fechar)
        self.after(100, self._ler_fila)
        self.after(300, self._conferir_motor)
        if not atualizar.copia_de_desenvolvimento():
            threading.Thread(target=self._conferir_versao, daemon=True).start()

    # ---------- interface ----------
    def _montar(self):
        raiz = tk.Frame(self, bg=tema.FUNDO, padx=px(22), pady=px(18))
        raiz.pack(fill="both", expand=True)
        self.raiz_conteudo = raiz

        topo = tk.Frame(raiz, bg=tema.FUNDO)
        topo.pack(fill="x", pady=(0, px(14)))
        self.topo = topo
        tema.rotulo(topo, f"versão {atualizar.versao_local()}", 9, tema.APAGADO).pack(side="right", anchor="n")
        if self.icones:
            tk.Label(topo, image=self.icones[48], bg=tema.FUNDO, bd=0).pack(side="left", padx=(0, px(12)))
        nomes = tk.Frame(topo, bg=tema.FUNDO)
        nomes.pack(side="left")
        linha = tk.Frame(nomes, bg=tema.FUNDO)
        linha.pack(anchor="w")
        tema.rotulo(linha, "Upscale de Vídeo", 18, tema.TEXTO, "bold").pack(side="left")
        tema.rotulo(linha, f"por {ASSINATURA}", 11, tema.DESTAQUE2, "bold").pack(
            side="left", anchor="s", padx=(px(10), 0), pady=(0, px(4)))
        tema.rotulo(nomes, "Amplie vídeos em baixa resolução direto na sua placa de vídeo.",
                    10, tema.SUAVE).pack(anchor="w")

        # --- rodape fixo: progresso e botoes (montado antes para nunca ser empurrado para fora)
        rodape = tk.Frame(raiz, bg=tema.FUNDO)
        rodape.pack(side="bottom", fill="x")
        tk.Frame(rodape, bg=tema.BORDA, height=1).pack(fill="x", pady=(px(14), px(12)))
        self.status = tema.rotulo(rodape, "", 10, tema.TEXTO, anchor="w", justify="left",
                                  wraplength=px(760))
        self.status.pack(fill="x")
        self.barra = tema.BarraProgresso(rodape)
        self.barra.pack(fill="x", pady=(px(8), px(12)))
        linha = tk.Frame(rodape, bg=tema.FUNDO)
        linha.pack(fill="x")
        self.b_comecar = tema.Botao(linha, "Começar", self._comecar, "primario", 11,
                                    padx=px(26), pady=px(8))
        self.b_comecar.pack(side="left")
        self.b_cancelar = tema.Botao(linha, "Cancelar", self._cancelar, pady=px(8))
        self.b_cancelar.pack(side="left", padx=px(8))
        self.b_cancelar.ligar(False)
        self.b_abrir = tema.Botao(linha, "Abrir pasta do resultado", self._abrir_pasta, pady=px(8))
        self.b_abrir.pack(side="right")
        self.b_abrir.ligar(False)

        # --- opcoes (tambem de baixo para cima, para a lista ficar com o espaco que sobrar)
        linha = tk.Frame(raiz, bg=tema.FUNDO)
        linha.pack(side="bottom", fill="x", pady=(px(12), 0))
        tema.rotulo(linha, "Salvar em:", 10, tema.SUAVE).pack(side="left")
        self.rotulo_pasta = tema.rotulo(linha, "mesma pasta do vídeo original", 10, tema.TEXTO)
        self.rotulo_pasta.pack(side="left", padx=px(6))
        self.b_pasta = tema.Botao(linha, "Escolher pasta...", self._escolher_pasta, tamanho=9, pady=px(4))
        self.b_pasta.pack(side="right")

        self.caixa_teste = tema.Caixa(
            raiz, f"Teste: processar só os primeiros {SEGUNDOS_TESTE} segundos de cada vídeo",
            self.teste, self._atualizar_estimativas)
        self.caixa_teste.pack(side="bottom", anchor="w", pady=(px(8), 0))
        self.caixa_cores = tema.Caixa(raiz, "Manter as cores do vídeo original (recomendado)",
                                      self.manter_cores)
        self.caixa_cores.pack(side="bottom", anchor="w", pady=(px(14), 0))

        cartoes = tk.Frame(raiz, bg=tema.FUNDO)
        cartoes.pack(side="bottom", fill="x")
        self.cartoes: dict[str, CartaoModo] = {}
        for n, modo in enumerate(upscaler.MODOS):
            cartao = CartaoModo(cartoes, modo, self.escolher_modo)
            cartao.grid(row=0, column=n, sticky="nsew", padx=(0 if n == 0 else px(10), 0))
            cartoes.columnconfigure(n, weight=1, uniform="cartao")
            self.cartoes[modo] = cartao
        tema.titulo_secao(raiz, "Qualidade").pack(side="bottom", anchor="w", pady=(px(16), px(6)))

        self.seg_resolucao = tema.Segmentos(raiz, RESOLUCOES, 1080, lambda v: self._mudou_resolucao())
        self.seg_resolucao.pack(side="bottom", anchor="w")
        tema.titulo_secao(raiz, "Resolução final").pack(side="bottom", anchor="w", pady=(px(16), px(6)))

        # --- lista de videos
        cabecalho = tk.Frame(raiz, bg=tema.FUNDO)
        cabecalho.pack(fill="x", pady=(0, px(6)))
        tema.titulo_secao(cabecalho, "Vídeos").pack(side="left", anchor="s")
        self.b_limpar = tema.Botao(cabecalho, "Limpar lista", self._limpar, "discreto", 9, pady=px(4))
        self.b_limpar.configure(bg=tema.FUNDO)
        self.b_limpar._base = self.b_limpar._apagado = tema.FUNDO
        self.b_limpar.pack(side="right")
        self.b_adicionar = tema.Botao(cabecalho, "+  Adicionar vídeos", self._escolher, tamanho=9, pady=px(4))
        self.b_adicionar.pack(side="right", padx=px(6))
        self.lista = tema.ListaRolavel(raiz, px(150))
        self.lista.pack(fill="both", expand=True)
        self.vazio = tema.rotulo(
            self.lista.dentro,
            "Nenhum vídeo na lista ainda.\n\nClique aqui para adicionar, ou arraste os arquivos em cima do Iniciar.bat.",
            10, tema.SUAVE, pady=px(34), cursor="hand2", justify="center")
        self.vazio.bind("<Button-1>", lambda e: self.trabalhando or self._escolher())

        self.escolher_modo("rapido")

    def _travar(self, travado: bool):
        livre = not travado
        for b in (self.b_adicionar, self.b_limpar, self.b_pasta, self.b_comecar):
            b.ligar(livre)
        self.b_cancelar.ligar(travado)
        self.seg_resolucao.ligar(livre)
        self.caixa_teste.ligar(livre)
        self.caixa_cores.ligar(livre)
        for cartao in self.cartoes.values():
            cartao.ativo = livre
            cartao.pintar(cartao.modo == self.modo)
        for linha in self.linhas:
            linha.ligar(livre)

    def escolher_modo(self, modo: str):
        self.modo = modo
        for cartao in self.cartoes.values():
            cartao.pintar(cartao.modo == modo)

    def _mudou_resolucao(self):
        for linha in self.linhas:
            linha.descrever(self.seg_resolucao.valor)

    def _atualizar_estimativas(self):
        prontas = [l.info for l in self.linhas if l.info]
        for modo, cartao in self.cartoes.items():
            if prontas:
                total = 0.0
                for i in prontas:
                    segundos = min(i.duracao, SEGUNDOS_TESTE) if self.teste.get() else i.duracao
                    total += upscaler.estimar_segundos(modo, segundos * float(i.fps), i.largura, i.altura)
                alvo = "o teste" if self.teste.get() else ("este vídeo" if len(prontas) == 1 else "a lista")
                cartao.tempo.configure(text=f"≈ {upscaler.formatar_tempo(total)} para {alvo}")
            else:
                segundos = upscaler.estimar_segundos(modo, 240)
                cartao.tempo.configure(text=f"≈ {upscaler.formatar_tempo(segundos)} por clipe de 10 s")

    # ---------- lista de videos ----------
    def _adicionar(self, caminho: Path):
        if not (caminho.is_file() and caminho.suffix.lower() in EXTENSOES):
            return
        if any(l.caminho == caminho for l in self.linhas):
            return
        linha = Linha(self, caminho)
        self.linhas.append(linha)
        threading.Thread(target=self._ler_video, args=(linha,), daemon=True).start()

    def _ler_video(self, linha: Linha):
        try:
            info = upscaler.analisar(linha.caminho)
            png = upscaler.miniatura(linha.caminho, px(MINIATURA[0]), px(MINIATURA[1]), tema.PAINEL2[1:])
            self.fila.put(("info", linha, info, png))
        except Exception as e:  # arquivo que nao e video, ffmpeg ausente...
            self.fila.put(("info_erro", linha, str(e)))

    def _atualizar_lista(self):
        if self.linhas:
            self.vazio.pack_forget()
        else:
            self.vazio.pack(fill="both", expand=True)
        self._atualizar_estimativas()

    def _escolher(self):
        tipos = [("Vídeos", " ".join("*" + e for e in EXTENSOES)), ("Todos os arquivos", "*.*")]
        for a in filedialog.askopenfilenames(title="Escolha os vídeos", filetypes=tipos):
            self._adicionar(Path(a))
        self._atualizar_lista()

    def remover(self, linha: Linha):
        linha.quadro.destroy()
        self.linhas.remove(linha)
        self._atualizar_lista()

    def _limpar(self):
        for linha in list(self.linhas):
            linha.quadro.destroy()
        self.linhas.clear()
        self._atualizar_lista()

    def _escolher_pasta(self):
        pasta = filedialog.askdirectory(title="Onde salvar os vídeos ampliados")
        if pasta:
            self.pasta_saida = Path(pasta)
            self.rotulo_pasta.configure(text=str(self.pasta_saida))

    def _abrir_pasta(self):
        if self.ultima_saida and self.ultima_saida.parent.is_dir():
            os.startfile(self.ultima_saida.parent)

    # ---------- comparacao ----------
    def abrir_comparador(self, linha: Linha):
        janela = self.comparadores.get(linha.caminho)
        if janela is None or not janela.winfo_exists():
            try:
                janela = Comparador(self, linha.caminho, self.escolher_modo)
            except ErroUpscale as e:
                messagebox.showerror("Upscale de Vídeo", str(e))
                return
            self.comparadores[linha.caminho] = janela
        for nome, caminho, modo in linha.versoes:
            if caminho.exists() and not any(
                    v["nome"] == nome and v["caminho"] == caminho for v in janela.versoes):
                janela.adicionar(nome, caminho, modo)
        janela.lift()
        janela.focus_set()

    def testar_qualidades(self, linha: Linha):
        """Processa os primeiros segundos em todos os modos e abre a comparacao."""
        if self.trabalhando:
            return
        if self.pasta_temp is None:
            self.pasta_temp = Path(tempfile.mkdtemp(prefix="upscale_comparar_"))
        self._iniciar_trabalho()
        threading.Thread(target=self._trabalhar_teste, daemon=True,
                         args=(linha, self.seg_resolucao.valor, self.manter_cores.get())).start()

    def _trabalhar_teste(self, linha: Linha, lado: int, cores: bool):
        modos = list(upscaler.MODOS)
        self.fila.put(("linha", linha, "Testando as qualidades...", tema.SUAVE))
        try:
            for n, modo in enumerate(modos, 1):
                nome = upscaler.NOMES_MODOS[modo]
                self.contador += 1
                destino = self.pasta_temp / f"{self.contador:03d}_{modo}_{lado}p.mp4"
                prefixo = f"Teste de qualidades · {nome} ({n} de {len(modos)}) — "
                upscaler.ampliar(linha.caminho, destino, lado, modo,
                                 lambda p, pre=prefixo: self.fila.put(("progresso", p, pre)),
                                 self.cancelar, SEGUNDOS_TESTE, cores)
                self.fila.put(("versao", linha, nome, destino, modo, n == 1))
            self.fila.put(("linha", linha, "Teste pronto. Compare em “Antes e depois”.", tema.OK))
            self.fila.put(("fim_teste", "Teste das qualidades pronto. A comparação está aberta."))
        except Cancelado:
            self.fila.put(("linha", linha, "Teste cancelado.", tema.SUAVE))
            self.fila.put(("fim_teste", "Teste cancelado."))
        except Exception as e:
            self.fila.put(("linha", linha, "O teste falhou.", tema.ERRO))
            self.fila.put(("fim_teste", "O teste falhou.", str(e)))

    # ---------- atualizacao ----------
    def _conferir_versao(self):
        achado = atualizar.consultar()
        if achado:
            self.fila.put(("versao_nova", *achado))

    def _mostrar_aviso(self, versao: str, novidades: list):
        self.aviso = tk.Frame(self.raiz_conteudo, bg=tema.PAINEL2)
        self.aviso.pack(fill="x", pady=(0, px(14)), after=self.topo)
        tk.Frame(self.aviso, bg=tema.DESTAQUE, width=px(4)).pack(side="left", fill="y")
        tema.rotulo(self.aviso, f"Saiu a versão {versao} do aplicativo.", 10, tema.TEXTO, "bold").pack(
            side="left", padx=(px(12), 0), pady=px(10))
        tema.Botao(self.aviso, "Depois", self.aviso.destroy, tamanho=9, pady=px(4)).pack(
            side="right", padx=(0, px(10)))
        self.b_atualizar = tema.Botao(self.aviso, "Ver novidades e atualizar",
                                      lambda: self._atualizar(versao, novidades), "primario", 9,
                                      pady=px(4))
        self.b_atualizar.pack(side="right", padx=px(8))

    def _atualizar(self, versao: str, novidades: list):
        if self.trabalhando:
            messagebox.showinfo("Upscale de Vídeo", "Espere o processamento terminar para atualizar.")
            return
        lista = "\n".join(f"•  {n}" for n in novidades) or "Melhorias gerais."
        if not messagebox.askyesno(
                "Atualizar o aplicativo",
                f"A versão {versao} traz:\n\n{lista}\n\n"
                "Atualizar agora? O aplicativo fecha e abre de novo, já na versão nova."):
            return
        self._iniciar_trabalho()
        self.b_cancelar.ligar(False)
        self.b_atualizar.ligar(False)
        self.status.configure(text="Baixando a atualização...")

        def baixar():
            try:
                self.fila.put(("atualizado", atualizar.instalar()))
            except Exception as e:  # rede, disco, pacote com defeito
                self.fila.put(("atualizar_erro", str(e)))

        threading.Thread(target=baixar, daemon=True).start()

    # ---------- motor ----------
    def _conferir_motor(self):
        if upscaler.motor_instalado():
            self._livre("Adicione um ou mais vídeos e clique em Começar.")
            return
        if not messagebox.askyesno(
            "Instalar o motor de upscale",
            "É preciso baixar o motor de upscale Real-ESRGAN e os modelos (até 46 MB), "
            "das páginas dos projetos no GitHub.\n\nBaixar agora?"):
            self._livre("Sem o motor não dá para ampliar. Feche e abra o aplicativo para baixar.")
            self.b_comecar.ligar(False)
            return
        self._iniciar_trabalho()
        self.b_cancelar.ligar(False)

        def baixar():
            try:
                upscaler.instalar_motor(lambda p: self.fila.put(("progresso", p, "")))
                self.fila.put(("motor_ok",))
            except Exception as e:  # rede, disco, arquivo corrompido
                self.fila.put(("motor_erro", str(e)))

        threading.Thread(target=baixar, daemon=True).start()

    # ---------- processamento ----------
    def _iniciar_trabalho(self):
        self.cancelar.clear()
        self.trabalhando = True
        self._travar(True)

    def _comecar(self):
        if not self.linhas:
            messagebox.showinfo("Upscale de Vídeo", "Adicione pelo menos um vídeo.")
            return
        self._iniciar_trabalho()
        self.b_abrir.ligar(False)
        for linha in self.linhas:
            linha.marcar("Na fila")
        args = (list(self.linhas), self.seg_resolucao.valor, self.modo,
                SEGUNDOS_TESTE if self.teste.get() else None, self.pasta_saida,
                self.manter_cores.get())
        threading.Thread(target=self._trabalhar, args=args, daemon=True).start()

    def _trabalhar(self, linhas, lado, modo, limite, pasta, cores):
        prontos, erros = [], []
        nome_modo = upscaler.NOMES_MODOS[modo]
        for n, linha in enumerate(linhas, 1):
            video = linha.caminho
            prefixo = f"[{n}/{len(linhas)}] {video.name} — "
            self.fila.put(("linha", linha, "Processando...", tema.DESTAQUE2))
            try:
                destino = upscaler.nome_saida(video, lado, pasta, "_teste" if limite else "")
                upscaler.ampliar(video, destino, lado, modo,
                                 lambda p, pre=prefixo: self.fila.put(("progresso", p, pre)),
                                 self.cancelar, limite, cores)
                prontos.append(destino)
                self.fila.put(("versao", linha, f"{nome_modo} {lado}p", destino, None, False))
                self.fila.put(("linha", linha, f"Pronto  ✓  {destino.name}", tema.OK))
            except Cancelado:
                self.fila.put(("linha", linha, "Cancelado", tema.SUAVE))
                self.fila.put(("fim", prontos, erros, True))
                return
            except ErroUpscale as e:
                erros.append(f"{video.name}: {e}")
                self.fila.put(("linha", linha, "Erro", tema.ERRO))
            except Exception as e:  # nao deixa um video ruim derrubar a fila inteira
                erros.append(f"{video.name}: erro inesperado ({e})")
                self.fila.put(("linha", linha, "Erro", tema.ERRO))
        self.fila.put(("fim", prontos, erros, False))

    def _cancelar(self):
        self.cancelar.set()
        self.status.configure(text="Cancelando...")
        self.b_cancelar.ligar(False)

    def _ler_fila(self):
        try:
            while True:
                self._tratar(self.fila.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._ler_fila)

    def _tratar(self, msg: tuple):
        tipo = msg[0]
        if tipo == "progresso":
            p: Progresso = msg[1]
            if p.total:
                self.barra.definir(p.feitos / p.total)
                if p.etapa.startswith("Baixando"):
                    detalhe = f"{p.feitos / 1e6:.0f} de {p.total / 1e6:.0f} MB"
                else:
                    detalhe = (f"quadro {p.feitos} de {p.total}  ·  "
                               f"resta {upscaler.formatar_tempo(p.restante_s)}")
                self.status.configure(text=f"{msg[2]}{p.etapa}\n{detalhe}")
            else:
                self.status.configure(text=f"{msg[2]}{p.etapa}")
        elif tipo == "info":
            _, linha, info, png = msg
            if linha in self.linhas:
                linha.info = info
                linha.descrever(self.seg_resolucao.valor)
                if png:
                    linha.foto = tk.PhotoImage(master=self, data=png)
                    linha.miniatura.configure(image=linha.foto)
                self._atualizar_estimativas()
        elif tipo == "info_erro":
            if msg[1] in self.linhas:
                msg[1].dados.configure(text="Não consegui ler este arquivo.", fg=tema.ERRO)
        elif tipo == "linha":
            if msg[1] in self.linhas:
                msg[1].marcar(msg[2], msg[3])
        elif tipo == "versao":
            _, linha, nome, caminho, modo, abrir = msg
            if linha in self.linhas:
                linha.guardar_versao(nome, caminho, modo)
                janela = self.comparadores.get(linha.caminho)
                if abrir or (janela is not None and janela.winfo_exists()):
                    self.abrir_comparador(linha)
        elif tipo == "versao_nova":
            self._mostrar_aviso(msg[1], msg[2])
        elif tipo == "atualizado":
            self.trabalhando = False
            atualizar.reiniciar()
            self._fechar()
        elif tipo == "atualizar_erro":
            self._livre("A atualização não foi concluída. O aplicativo continua na versão atual.")
            self.b_atualizar.ligar(True)
            messagebox.showerror("Upscale de Vídeo", msg[1][:1500])
        elif tipo == "motor_ok":
            self._livre("Motor instalado. Adicione os vídeos e clique em Começar.")
        elif tipo == "motor_erro":
            self._livre("Não consegui baixar o motor: " + msg[1])
            self.b_comecar.ligar(False)
        elif tipo == "fim_teste":
            self._livre(msg[1])
            if len(msg) > 2:
                messagebox.showerror("Upscale de Vídeo", msg[2][:1500])
        elif tipo == "fim":
            self._terminar(*msg[1:])

    def _livre(self, texto: str):
        self.trabalhando = False
        self._travar(False)
        self.barra.definir(0)
        self.status.configure(text=texto)

    def _terminar(self, prontos, erros, cancelado):
        partes = []
        if cancelado:
            partes.append("Cancelado.")
        if prontos:
            self.ultima_saida = prontos[-1]
            partes.append(f"{len(prontos)} vídeo(s) pronto(s). Clique em “Antes e depois” para comparar.")
        if erros:
            partes.append(f"{len(erros)} com erro.")
        self._livre(" ".join(partes) or "Nada foi processado.")
        if prontos:
            self.b_abrir.ligar(True)
            self.barra.definir(0 if cancelado else 1)
        if erros:
            messagebox.showerror("Upscale de Vídeo", "\n\n".join(erros)[:1500])

    def _fechar(self):
        if self.trabalhando and not messagebox.askyesno(
                "Upscale de Vídeo", "Ainda está processando. Cancelar e fechar?"):
            return
        self.cancelar.set()
        for janela in self.comparadores.values():
            if janela.winfo_exists():
                janela.fechar()
        if self.pasta_temp:
            shutil.rmtree(self.pasta_temp, ignore_errors=True)
        self.destroy()


if __name__ == "__main__":
    tema.ativar_dpi()
    tema.identificar_app("iacomthiago.upscaledevideo")
    App(sys.argv[1:]).mainloop()
