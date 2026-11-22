"""Janela do aplicativo de upscale. Abra pelo Iniciar.bat (ou: python app.py)."""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import upscaler
from upscaler import Cancelado, ErroUpscale, Progresso

EXTENSOES = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
RESOLUCOES = [(1080, "1080p (Full HD)"), (720, "720p (HD)"), (1440, "1440p (2K)")]
SEGUNDOS_TESTE = 3


class App(tk.Tk):
    def __init__(self, arquivos: list[str]):
        super().__init__()
        self.title("Upscale de Vídeo")
        self.minsize(620, 560)
        self.fila: "queue.Queue[tuple]" = queue.Queue()
        self.cancelar = threading.Event()
        self.trabalhando = False
        self.videos: list[Path] = []
        self.pasta_saida: Path | None = None
        self.ultima_saida: Path | None = None

        self.resolucao = tk.IntVar(value=1080)
        self.modo = tk.StringVar(value="rapido")
        self.teste = tk.BooleanVar(value=False)

        self._montar()
        for a in arquivos:
            self._adicionar(Path(a))
        self.protocol("WM_DELETE_WINDOW", self._fechar)
        self.after(100, self._ler_fila)
        self.after(300, self._conferir_motor)

    # ---------- interface ----------
    def _montar(self):
        ttk.Style(self).configure("Titulo.TLabel", font=("Segoe UI", 10, "bold"))
        raiz = ttk.Frame(self, padding=14)
        raiz.pack(fill="both", expand=True)

        ttk.Label(raiz, text="Vídeos", style="Titulo.TLabel").pack(anchor="w")
        quadro = ttk.Frame(raiz)
        quadro.pack(fill="both", expand=True, pady=(4, 0))
        self.lista = tk.Listbox(quadro, height=6, selectmode="extended", activestyle="none")
        barra = ttk.Scrollbar(quadro, command=self.lista.yview)
        self.lista.configure(yscrollcommand=barra.set)
        self.lista.pack(side="left", fill="both", expand=True)
        barra.pack(side="left", fill="y")

        botoes = ttk.Frame(raiz)
        botoes.pack(fill="x", pady=6)
        self.b_adicionar = ttk.Button(botoes, text="Adicionar vídeos...", command=self._escolher)
        self.b_adicionar.pack(side="left")
        self.b_remover = ttk.Button(botoes, text="Remover selecionados", command=self._remover)
        self.b_remover.pack(side="left", padx=6)
        self.b_limpar = ttk.Button(botoes, text="Limpar lista", command=self._limpar)
        self.b_limpar.pack(side="left")

        ttk.Label(raiz, text="Resolução final", style="Titulo.TLabel").pack(anchor="w", pady=(10, 2))
        linha = ttk.Frame(raiz)
        linha.pack(fill="x")
        self.opcoes: list[ttk.Widget] = []
        for valor, texto in RESOLUCOES:
            r = ttk.Radiobutton(linha, text=texto, value=valor, variable=self.resolucao)
            r.pack(side="left", padx=(0, 16))
            self.opcoes.append(r)

        ttk.Label(raiz, text="Qualidade", style="Titulo.TLabel").pack(anchor="w", pady=(10, 2))
        for chave, texto in upscaler.DESCRICAO_MODOS.items():
            r = ttk.Radiobutton(raiz, text=texto, value=chave, variable=self.modo)
            r.pack(anchor="w")
            self.opcoes.append(r)

        c = ttk.Checkbutton(raiz, variable=self.teste,
                            text=f"Teste: processar só os primeiros {SEGUNDOS_TESTE} segundos de cada vídeo")
        c.pack(anchor="w", pady=(10, 0))
        self.opcoes.append(c)

        linha = ttk.Frame(raiz)
        linha.pack(fill="x", pady=(10, 0))
        ttk.Label(linha, text="Salvar em:").pack(side="left")
        self.rotulo_pasta = ttk.Label(linha, text="mesma pasta do vídeo original")
        self.rotulo_pasta.pack(side="left", padx=6)
        self.b_pasta = ttk.Button(linha, text="Escolher pasta...", command=self._escolher_pasta)
        self.b_pasta.pack(side="right")

        ttk.Separator(raiz).pack(fill="x", pady=12)
        self.status = ttk.Label(raiz, text="Adicione um ou mais vídeos e clique em Começar.",
                                wraplength=580, justify="left")
        self.status.pack(anchor="w")
        self.barra = ttk.Progressbar(raiz, maximum=1000)
        self.barra.pack(fill="x", pady=6)

        linha = ttk.Frame(raiz)
        linha.pack(fill="x")
        self.b_comecar = ttk.Button(linha, text="Começar", command=self._comecar)
        self.b_comecar.pack(side="left")
        self.b_cancelar = ttk.Button(linha, text="Cancelar", command=self._cancelar, state="disabled")
        self.b_cancelar.pack(side="left", padx=6)
        self.b_abrir = ttk.Button(linha, text="Abrir pasta do resultado", command=self._abrir_pasta,
                                  state="disabled")
        self.b_abrir.pack(side="right")

    def _travar(self, travado: bool):
        estado = "disabled" if travado else "normal"
        for w in (self.b_adicionar, self.b_remover, self.b_limpar, self.b_pasta,
                  self.b_comecar, *self.opcoes):
            w.configure(state=estado)
        self.b_cancelar.configure(state="normal" if travado else "disabled")

    # ---------- lista de videos ----------
    def _adicionar(self, caminho: Path):
        if caminho.is_file() and caminho.suffix.lower() in EXTENSOES and caminho not in self.videos:
            self.videos.append(caminho)
            self.lista.insert("end", f"{caminho.name}    ({caminho.parent})")

    def _escolher(self):
        tipos = [("Vídeos", " ".join("*" + e for e in EXTENSOES)), ("Todos os arquivos", "*.*")]
        for a in filedialog.askopenfilenames(title="Escolha os vídeos", filetypes=tipos):
            self._adicionar(Path(a))

    def _remover(self):
        for i in reversed(self.lista.curselection()):
            self.lista.delete(i)
            del self.videos[i]

    def _limpar(self):
        self.lista.delete(0, "end")
        self.videos.clear()

    def _escolher_pasta(self):
        pasta = filedialog.askdirectory(title="Onde salvar os vídeos ampliados")
        if pasta:
            self.pasta_saida = Path(pasta)
            self.rotulo_pasta.configure(text=str(self.pasta_saida))

    def _abrir_pasta(self):
        if self.ultima_saida and self.ultima_saida.parent.is_dir():
            os.startfile(self.ultima_saida.parent)

    # ---------- motor ----------
    def _conferir_motor(self):
        if upscaler.motor_instalado():
            return
        if not messagebox.askyesno(
            "Instalar o motor de upscale",
            "Na primeira vez é preciso baixar o motor Real-ESRGAN (≈ 43 MB), "
            "da página oficial do projeto no GitHub.\n\nBaixar agora?"):
            self.status.configure(text="Sem o motor não dá para ampliar. Feche e abra o aplicativo para baixar.")
            self.b_comecar.configure(state="disabled")
            return
        self.trabalhando = True
        self._travar(True)
        self.b_cancelar.configure(state="disabled")

        def baixar():
            try:
                upscaler.instalar_motor(lambda p: self.fila.put(("progresso", p, "")))
                self.fila.put(("motor_ok",))
            except Exception as e:  # rede, disco, arquivo corrompido
                self.fila.put(("motor_erro", str(e)))

        threading.Thread(target=baixar, daemon=True).start()

    # ---------- processamento ----------
    def _comecar(self):
        if not self.videos:
            messagebox.showinfo("Upscale de Vídeo", "Adicione pelo menos um vídeo.")
            return
        self.cancelar.clear()
        self.trabalhando = True
        self._travar(True)
        self.b_abrir.configure(state="disabled")
        args = (list(self.videos), self.resolucao.get(), self.modo.get(),
                SEGUNDOS_TESTE if self.teste.get() else None, self.pasta_saida)
        threading.Thread(target=self._trabalhar, args=args, daemon=True).start()

    def _trabalhar(self, videos, lado, modo, limite, pasta):
        prontos, erros = [], []
        for n, video in enumerate(videos, 1):
            prefixo = f"[{n}/{len(videos)}] {video.name} — "
            try:
                destino = upscaler.nome_saida(video, lado, pasta, "_teste" if limite else "")
                upscaler.ampliar(video, destino, lado, modo,
                                 lambda p, pre=prefixo: self.fila.put(("progresso", p, pre)),
                                 self.cancelar, limite)
                prontos.append(destino)
            except Cancelado:
                self.fila.put(("fim", prontos, erros, True))
                return
            except ErroUpscale as e:
                erros.append(f"{video.name}: {e}")
            except Exception as e:  # nao deixa um video ruim derrubar a fila inteira
                erros.append(f"{video.name}: erro inesperado ({e})")
        self.fila.put(("fim", prontos, erros, False))

    def _cancelar(self):
        self.cancelar.set()
        self.status.configure(text="Cancelando...")
        self.b_cancelar.configure(state="disabled")

    def _ler_fila(self):
        try:
            while True:
                msg = self.fila.get_nowait()
                if msg[0] == "progresso":
                    p: Progresso = msg[1]
                    if p.total:
                        self.barra.configure(value=1000 * p.feitos / p.total)
                        if p.etapa.startswith("Baixando"):
                            detalhe = f"{p.feitos / 1e6:.0f} de {p.total / 1e6:.0f} MB"
                        else:
                            detalhe = (f"quadro {p.feitos} de {p.total} · "
                                       f"resta {upscaler.formatar_tempo(p.restante_s)}")
                        self.status.configure(text=f"{msg[2]}{p.etapa}\n{detalhe}")
                    else:
                        self.status.configure(text=f"{msg[2]}{p.etapa}")
                elif msg[0] == "motor_ok":
                    self._livre("Motor instalado. Adicione os vídeos e clique em Começar.")
                elif msg[0] == "motor_erro":
                    self._livre("Não consegui baixar o motor: " + msg[1])
                    self.b_comecar.configure(state="disabled")
                elif msg[0] == "fim":
                    self._terminar(*msg[1:])
        except queue.Empty:
            pass
        self.after(100, self._ler_fila)

    def _livre(self, texto: str):
        self.trabalhando = False
        self._travar(False)
        self.barra.configure(value=0)
        self.status.configure(text=texto)

    def _terminar(self, prontos, erros, cancelado):
        if prontos:
            self.ultima_saida = prontos[-1]
        partes = []
        if cancelado:
            partes.append("Cancelado.")
        if prontos:
            partes.append(f"{len(prontos)} vídeo(s) pronto(s). Último: {prontos[-1].name}")
        if erros:
            partes.append(f"{len(erros)} com erro.")
        self._livre(" ".join(partes) or "Nada foi processado.")
        if prontos:
            self.b_abrir.configure(state="normal")
            self.barra.configure(value=1000 if not cancelado else 0)
        if erros:
            messagebox.showerror("Upscale de Vídeo", "\n\n".join(erros)[:1500])

    def _fechar(self):
        if self.trabalhando and not messagebox.askyesno(
                "Upscale de Vídeo", "Ainda está processando. Cancelar e fechar?"):
            return
        self.cancelar.set()
        self.destroy()


if __name__ == "__main__":
    App(sys.argv[1:]).mainloop()
