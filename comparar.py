"""Tela de comparacao: toca duas versoes do mesmo video lado a lado, em sincronia.

O ffmpeg decodifica as duas versoes, recorta a mesma regiao de cada uma e entrega
os quadros prontos; a janela so exibe. A versao menor (o original em 480p) e
esticada ate o tamanho da maior, como um player faria, para a comparacao ser justa.
"""
from __future__ import annotations

import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

import tema
import upscaler
from tema import px

ESPACO = 6  # faixa escura entre os dois lados, em pixels
ZOOMS = [(0, "Quadro inteiro"), (1, "100%"), (2, "200%"), (4, "400%")]


def _par(n: float) -> int:
    return max(2, int(n) // 2 * 2)


class Comparador(tk.Toplevel):
    def __init__(self, mestre, original: Path, ao_usar_modo: Optional[Callable[[str], None]] = None):
        super().__init__(mestre)
        self.title(f"Comparar — {original.name}")
        self.configure(bg=tema.FUNDO)
        largura = min(px(1560), self.winfo_screenwidth() - px(80))
        altura = min(px(820), self.winfo_screenheight() - px(120))
        self.geometry(f"{largura}x{altura}")
        self.minsize(px(860), px(480))
        tema.barra_escura(self)

        self.ao_usar_modo = ao_usar_modo
        self.versoes: list[dict] = []
        self.esq, self.dir = 0, 0
        self.zoom = 0
        self.cx = self.cy = 0.5
        self.ref = (2, 2)
        self.fps = 24.0
        self.total = 1
        self.pos = 0
        self.tocando = True
        self.vivo = True

        self.proc: Optional[subprocess.Popen] = None
        self.parar = threading.Event()
        self.quadros: "queue.Queue" = queue.Queue(maxsize=4)
        self.proximo = 0.0
        self.relogio_ok = False
        self.imagem: Optional[tk.PhotoImage] = None
        self.tamanho_imagem = (0, 0)
        self.geo: dict = {}
        self._pendente = None
        self._arrasto = None

        self._montar()
        self.adicionar("Original", original)
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.bind("<Destroy>", lambda e: e.widget is self and self._encerrar())
        self.bind("<space>", lambda e: self._alternar())
        self.bind("<Left>", lambda e: self._passo(-1))
        self.bind("<Right>", lambda e: self._passo(1))
        self.after(8, self._tique)

    # ---------- interface ----------
    def _montar(self):
        topo = tk.Frame(self, bg=tema.FUNDO, padx=px(16), pady=px(12))
        topo.pack(fill="x")
        lado_e = tk.Frame(topo, bg=tema.FUNDO)
        lado_e.pack(side="left")
        tema.titulo_secao(lado_e, "Lado esquerdo").pack(anchor="w", pady=(0, px(4)))
        self.seg_esq = tema.Segmentos(lado_e, [], 0, lambda v: self._trocar("esq", v), 9)
        self.seg_esq.pack(anchor="w")
        lado_d = tk.Frame(topo, bg=tema.FUNDO)
        lado_d.pack(side="right")
        tema.titulo_secao(lado_d, "Lado direito").pack(anchor="e", pady=(0, px(4)))
        self.seg_dir = tema.Segmentos(lado_d, [], 0, lambda v: self._trocar("dir", v), 9)
        self.seg_dir.pack(anchor="e")

        rodape = tk.Frame(self, bg=tema.FUNDO, padx=px(16))
        rodape.pack(side="bottom", fill="x", pady=(0, px(12)))
        self.dica = tema.rotulo(rodape, "", 9, tema.SUAVE)
        self.dica.pack(side="left")
        self.area_usar = tk.Frame(rodape, bg=tema.FUNDO)
        self.area_usar.pack(side="right")

        controles = tk.Frame(self, bg=tema.FUNDO, padx=px(16), pady=px(10))
        controles.pack(side="bottom", fill="x")
        self.b_tocar = tema.Botao(controles, "⏸  Pausar", self._alternar, width=10)
        self.b_tocar.pack(side="left")
        self.seg_zoom = tema.Segmentos(controles, ZOOMS, 0, self._mudar_zoom, 9)
        self.seg_zoom.pack(side="right")
        tema.rotulo(controles, "Zoom", 9, tema.SUAVE).pack(side="right", padx=(px(16), px(8)))
        self.tempo = tema.rotulo(controles, "", 9, tema.SUAVE, width=30, anchor="e")
        self.tempo.pack(side="right")
        self.deslizador = tema.Deslizador(controles, self._buscar)
        self.deslizador.pack(side="left", fill="x", expand=True, padx=px(12))

        self.tela = tk.Canvas(self, bg=tema.PRETO, highlightthickness=0)
        self.tela.pack(fill="both", expand=True)
        self.item_imagem = self.tela.create_image(0, 0, anchor="center")
        self.itens_rotulo = []
        for _ in range(2):
            fundo = self.tela.create_rectangle(0, 0, 0, 0, fill=tema.PRETO, outline="")
            texto = self.tela.create_text(0, 0, anchor="nw", fill=tema.TEXTO, font=tema.fonte(9, "bold"))
            self.itens_rotulo.append((fundo, texto))
        self.tela.bind("<Configure>", lambda e: self._agendar(150))
        self.tela.bind("<Button-1>", self._pegar)
        self.tela.bind("<B1-Motion>", self._arrastar)
        self.tela.bind("<ButtonRelease-1>", lambda e: setattr(self, "_arrasto", None))
        self.tela.bind("<MouseWheel>", self._roda)
        self._atualizar_dica()

    def _atualizar_dica(self):
        if self.zoom:
            texto = "Arraste a imagem para olhar outra parte do quadro. Roda do mouse muda o zoom."
        else:
            texto = "Use o zoom em 100% ou 200% para enxergar a diferença de nitidez. Espaço pausa."
        self.dica.configure(text=texto)

    # ---------- versoes ----------
    def adicionar(self, nome: str, caminho: Path, modo: Optional[str] = None) -> None:
        """Inclui (ou substitui) uma versao do video na comparacao."""
        info = upscaler.analisar(caminho)
        nova = {"nome": nome, "caminho": caminho, "modo": modo, "info": info}
        existente = next((i for i, v in enumerate(self.versoes) if v["nome"] == nome), None)
        if existente is None:
            self.versoes.append(nova)
            if len(self.versoes) == 2:
                self.dir = 1
        else:
            self.versoes[existente] = nova
        if len(self.versoes) == 1:
            self.fps = float(info.fps)
        self.ref = max(((v["info"].largura, v["info"].altura) for v in self.versoes),
                       key=lambda t: t[0] * t[1])
        opcoes = [(i, v["nome"]) for i, v in enumerate(self.versoes)]
        self.seg_esq.definir_opcoes(opcoes)
        self.seg_dir.definir_opcoes(opcoes)
        self.seg_esq.escolher(self.esq, avisar=False)
        self.seg_dir.escolher(self.dir, avisar=False)
        self._montar_usar()
        self._recalcular_total()
        self._agendar(50)

    def _montar_usar(self):
        for w in self.area_usar.winfo_children():
            w.destroy()
        modos = [v for v in self.versoes if v["modo"]]
        if not (modos and self.ao_usar_modo):
            return
        tema.rotulo(self.area_usar, "Gostou de um?", 9, tema.SUAVE).pack(side="left", padx=(0, px(8)))
        for v in modos:
            tema.Botao(self.area_usar, f"Usar {v['nome']}", lambda v=v: self._usar(v), tamanho=9,
                       pady=px(4)).pack(side="left", padx=(px(6), 0))

    def _usar(self, versao: dict):
        self.ao_usar_modo(versao["modo"])
        self.dica.configure(text=f"Qualidade “{versao['nome']}” marcada na janela principal.")

    def _recalcular_total(self):
        duracao = min(self.versoes[i]["info"].duracao for i in (self.esq, self.dir))
        self.total = max(1, int(duracao * self.fps))
        self.pos = min(self.pos, self.total - 1)
        self.deslizador.definir(self.pos, self.total - 1)

    def _trocar(self, lado: str, indice: int):
        setattr(self, lado, indice)
        self._recalcular_total()
        self._agendar(0)

    # ---------- enquadramento ----------
    def _geometria(self) -> dict:
        rw, rh = self.ref
        livre_w = max(2, (self.tela.winfo_width() - ESPACO - px(24)) // 2)
        livre_h = max(2, self.tela.winfo_height() - px(24))
        if not self.zoom:
            fator = min(livre_w / rw, livre_h / rh, 1.0)
            return {"corte": None, "pw": _par(rw * fator), "ph": _par(rh * fator)}
        z = self.zoom
        cw, ch = min(rw, _par(livre_w / z)), min(rh, _par(livre_h / z))
        x = min(max(0, int(round(self.cx * rw - cw / 2))), rw - cw)
        y = min(max(0, int(round(self.cy * rh - ch / 2))), rh - ch)
        self.cx, self.cy = (x + cw / 2) / rw, (y + ch / 2) / rh  # ja com o limite da borda
        return {"corte": (cw, ch, x, y), "pw": cw * z, "ph": ch * z}

    def _filtro(self, geo: dict) -> str:
        rw, rh = self.ref
        partes = []
        for n, indice in enumerate((self.esq, self.dir)):
            info = self.versoes[indice]["info"]
            passos = []
            if (info.largura, info.altura) != (rw, rh):
                passos.append(f"scale={rw}:{rh}:flags=bicubic")
            if geo["corte"]:
                cw, ch, x, y = geo["corte"]
                passos.append(f"crop={cw}:{ch}:{x}:{y}")
                if self.zoom > 1:
                    passos.append(f"scale={geo['pw']}:{geo['ph']}:flags=neighbor")
            elif (rw, rh) != (geo["pw"], geo["ph"]):
                passos.append(f"scale={geo['pw']}:{geo['ph']}:flags=bicubic")
            passos.append("setsar=1")
            if n == 0:
                passos.append(f"pad=iw+{ESPACO}:ih:0:0:color=0x{tema.PRETO[1:]}")
            partes.append(f"[{n}:v]{','.join(passos)}[v{n}]")
        partes.append("[v0][v1]hstack=inputs=2:shortest=1[o]")
        return ";".join(partes)

    # ---------- reproducao ----------
    def _parar_proc(self):
        self.parar.set()
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        self.proc = None
        # Quadros ja lidos da leitura antiga nao podem aparecer depois (desfariam um pulo).
        self.quadros = queue.Queue(maxsize=4)

    def _iniciar(self):
        """(Re)começa a leitura a partir de `self.pos`; pausado, traz só um quadro."""
        self._parar_proc()
        if not self.vivo or len(self.versoes) < 1 or self.tela.winfo_width() < 50:
            return
        geo = self._geometria()
        self.geo = geo
        largura = 2 * geo["pw"] + ESPACO
        # Meio quadro antes do alvo: os dois videos caem no mesmo quadro mesmo com arredondamento.
        salto = ["-ss", f"{(self.pos - 0.5) / self.fps:.6f}"] if self.pos > 0 else []
        cmd = ["ffmpeg", "-v", "error"]
        for indice in (self.esq, self.dir):
            cmd += [*salto, "-i", str(self.versoes[indice]["caminho"])]
        cmd += ["-filter_complex", self._filtro(geo), "-map", "[o]", "-an"]
        if not self.tocando:
            cmd += ["-frames:v", "1"]
        cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     creationflags=upscaler.SEM_JANELA)
        self.parar = threading.Event()
        self.quadros = queue.Queue(maxsize=4)
        self.relogio_ok = False
        threading.Thread(target=self._ler, daemon=True,
                         args=(self.proc, self.quadros, self.parar, largura, geo["ph"], self.pos)).start()

    @staticmethod
    def _ler(proc, fila, parar, largura, altura, inicio):
        tamanho = largura * altura * 3
        indice = inicio
        while not parar.is_set():
            dados = proc.stdout.read(tamanho)
            item = (indice, largura, altura, dados) if len(dados) == tamanho else None
            while not parar.is_set():
                try:
                    fila.put(item, timeout=0.1)
                    break
                except queue.Full:
                    pass
            if item is None:
                return
            indice += 1

    def _tique(self):
        if not self.vivo:
            return
        agora = time.perf_counter()
        if not self.tocando or not self.relogio_ok or agora >= self.proximo:
            try:
                item = self.quadros.get_nowait()
            except queue.Empty:
                item = False
            if item is None:
                if self.tocando:  # chegou ao fim: volta ao começo
                    self.pos = 0
                    self._iniciar()
            elif item:
                self._mostrar(*item)
                if not self.relogio_ok:
                    self.relogio_ok, self.proximo = True, agora
                # se a leitura atrasar, o relogio acompanha em vez de acumular atraso
                self.proximo = max(self.proximo + 1 / self.fps, agora - 0.5 / self.fps)
        self.after(4, self._tique)

    def _mostrar(self, indice: int, largura: int, altura: int, dados: bytes):
        if (largura, altura) != self.tamanho_imagem:
            self.imagem = tk.PhotoImage(master=self, width=largura, height=altura)
            self.tamanho_imagem = (largura, altura)
            self.tela.itemconfigure(self.item_imagem, image=self.imagem)
        self.imagem.configure(data=b"P6\n%d %d\n255\n" % (largura, altura) + dados)
        self._posicionar(largura, altura)
        self.pos = min(indice, self.total - 1)
        self.deslizador.definir(self.pos)
        self._escrever_tempo()

    def _posicionar(self, largura: int, altura: int):
        cx, cy = self.tela.winfo_width() // 2, self.tela.winfo_height() // 2
        self.tela.coords(self.item_imagem, cx, cy)
        x0, y0 = cx - largura // 2, cy - altura // 2
        lado = (largura - ESPACO) // 2
        for n, indice in enumerate((self.esq, self.dir)):
            v = self.versoes[indice]
            extra = " (esticado)" if (v["info"].largura, v["info"].altura) != self.ref else ""
            texto = f"{v['nome']}  ·  {v['info'].largura}×{v['info'].altura}{extra}"
            fundo, item = self.itens_rotulo[n]
            x = x0 + n * (lado + ESPACO) + px(8)
            self.tela.itemconfigure(item, text=texto)
            self.tela.coords(item, x + px(6), y0 + px(8) + px(3))
            caixa = self.tela.bbox(item)
            self.tela.coords(fundo, caixa[0] - px(6), caixa[1] - px(3), caixa[2] + px(6), caixa[3] + px(3))
            self.tela.tag_raise(fundo)
            self.tela.tag_raise(item)

    def _escrever_tempo(self):
        def mmss(quadros):
            s = quadros / self.fps
            return f"{int(s // 60)}:{s % 60:04.1f}".replace(".", ",")
        self.tempo.configure(
            text=f"{mmss(self.pos)} / {mmss(self.total)}  ·  quadro {self.pos + 1} de {self.total}")

    # ---------- comandos ----------
    def _agendar(self, espera_ms: int):
        if self._pendente:
            self.after_cancel(self._pendente)
        self._pendente = self.after(espera_ms, self._reiniciar)

    def _reiniciar(self):
        self._pendente = None
        self._iniciar()

    def _alternar(self):
        self.tocando = not self.tocando
        self.b_tocar.configure(text="⏸  Pausar" if self.tocando else "▶  Tocar")
        if self.tocando:
            self._iniciar()
        else:
            self._parar_proc()

    def _passo(self, quanto: int):
        if self.tocando:
            self._alternar()
        self.pos = min(max(0, self.pos + quanto), self.total - 1)
        self._agendar(0)

    def _buscar(self, valor: float, final: bool):
        self.pos = min(int(valor), self.total - 1)
        self._escrever_tempo()
        self._agendar(0 if final else 90)

    def _mudar_zoom(self, zoom: int):
        self.zoom = zoom
        self.tela.configure(cursor="fleur" if zoom else "")
        self._atualizar_dica()
        self._agendar(0)

    def _roda(self, e):
        niveis = [z for z, _ in ZOOMS]
        novo = niveis.index(self.zoom) + (1 if e.delta > 0 else -1)
        if 0 <= novo < len(niveis):
            self.seg_zoom.escolher(niveis[novo])

    def _pegar(self, e):
        self._arrasto = (e.x, e.y)

    def _arrastar(self, e):
        if not (self.zoom and self._arrasto):
            return
        dx, dy = e.x - self._arrasto[0], e.y - self._arrasto[1]
        self._arrasto = (e.x, e.y)
        self.cx -= dx / self.zoom / self.ref[0]
        self.cy -= dy / self.zoom / self.ref[1]
        self._geometria()  # aplica o limite das bordas
        self._agendar(40)

    def _encerrar(self):
        self.vivo = False
        self._parar_proc()

    def fechar(self):
        self._encerrar()
        self.destroy()
