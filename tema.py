"""Visual do aplicativo: cores, fontes e os componentes usados nas janelas."""
from __future__ import annotations

import ctypes
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

FUNDO = "#13141a"
PAINEL = "#1c1e27"
PAINEL2 = "#272a37"
REALCE = "#33374a"
BORDA = "#363a4c"
PRETO = "#0b0c10"
TEXTO = "#eef0f6"
SUAVE = "#9aa1b5"
APAGADO = "#5d6274"
DESTAQUE = "#7c5cff"
DESTAQUE2 = "#9279ff"
OK = "#3ecf8e"
ERRO = "#ff6b6b"
FONTE = "Segoe UI"

_escala = 1.0


def ativar_dpi() -> None:
    """Sem isto o Windows estica a janela em telas com zoom e borra a comparacao."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def px(n: float) -> int:
    return int(round(n * _escala))


def fonte(tamanho: int, peso: str = "normal") -> tuple:
    return (FONTE, tamanho, peso)


def barra_escura(janela: tk.Misc) -> None:
    """Deixa a barra de titulo do Windows escura, combinando com o resto."""
    try:
        janela.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(janela.winfo_id())
        valor = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(valor), 4)
    except (AttributeError, OSError):
        pass


def preparar(janela: tk.Tk) -> None:
    global _escala
    _escala = janela.winfo_fpixels("1i") / 96
    janela.configure(bg=FUNDO)
    estilo = ttk.Style(janela)
    estilo.theme_use("clam")
    estilo.configure("Vertical.TScrollbar", background=REALCE, troughcolor=PAINEL, bordercolor=PAINEL,
                     lightcolor=REALCE, darkcolor=REALCE, arrowcolor=SUAVE, gripcount=0)
    estilo.map("Vertical.TScrollbar", background=[("active", APAGADO)])
    barra_escura(janela)


def rotulo(mestre, texto: str = "", tamanho: int = 10, cor: str = TEXTO, peso: str = "normal",
           fundo: Optional[str] = None, **kw) -> tk.Label:
    return tk.Label(mestre, text=texto, font=fonte(tamanho, peso), fg=cor,
                    bg=fundo or mestre["bg"], **kw)


def titulo_secao(mestre, texto: str) -> tk.Label:
    return rotulo(mestre, texto.upper(), 8, SUAVE, "bold")


class Botao(tk.Button):
    ESTILOS = {
        "primario": (DESTAQUE, DESTAQUE2, "#ffffff"),
        "normal": (PAINEL2, REALCE, TEXTO),
        "discreto": (PAINEL, PAINEL2, SUAVE),
    }

    def __init__(self, mestre, texto: str, comando: Callable, estilo: str = "normal",
                 tamanho: int = 10, **kw):
        base, sobre, letra = self.ESTILOS[estilo]
        kw.setdefault("padx", px(14))
        kw.setdefault("pady", px(6))
        super().__init__(mestre, text=texto, command=comando, bg=base, fg=letra,
                         activebackground=sobre, activeforeground=letra, disabledforeground=APAGADO,
                         relief="flat", bd=0, highlightthickness=0, cursor="hand2",
                         font=fonte(tamanho, "bold" if estilo == "primario" else "normal"), **kw)
        self._base, self._sobre = base, sobre
        self._apagado = PAINEL2 if estilo == "primario" else base
        self.bind("<Enter>", lambda e: self._pintar(self._sobre))
        self.bind("<Leave>", lambda e: self._pintar(self._base))

    def _pintar(self, cor: str) -> None:
        if self["state"] != "disabled":
            self.configure(bg=cor)

    def ligar(self, sim: bool) -> None:
        self.configure(state="normal" if sim else "disabled", cursor="hand2" if sim else "arrow",
                       bg=self._base if sim else self._apagado)


class Segmentos(tk.Frame):
    """Fileira de opcoes em que uma fica marcada (substitui os botoes de radio)."""

    def __init__(self, mestre, opcoes: list, valor, ao_mudar: Optional[Callable] = None,
                 tamanho: int = 10):
        super().__init__(mestre, bg=PAINEL2, padx=px(3), pady=px(3))
        self.valor = valor
        self.ao_mudar = ao_mudar
        self.tamanho = tamanho
        self.ativo = True
        self.itens: dict = {}
        self.definir_opcoes(opcoes)

    def definir_opcoes(self, opcoes: list) -> None:
        for w in self.itens.values():
            w.destroy()
        self.itens = {}
        for v, texto in opcoes:
            item = tk.Label(self, text=texto, font=fonte(self.tamanho), padx=px(14), pady=px(5),
                            cursor="hand2")
            item.pack(side="left")
            item.bind("<Button-1>", lambda e, v=v: self.ativo and self.escolher(v))
            item.bind("<Enter>", lambda e, v=v: self._pintar(sobre=v))
            item.bind("<Leave>", lambda e: self._pintar())
            self.itens[v] = item
        self._pintar()

    def escolher(self, valor, avisar: bool = True) -> None:
        mudou = valor != self.valor
        self.valor = valor
        self._pintar()
        if mudou and avisar and self.ao_mudar:
            self.ao_mudar(valor)

    def _pintar(self, sobre=None) -> None:
        for v, item in self.itens.items():
            if v == self.valor:
                item.configure(bg=DESTAQUE if self.ativo else APAGADO, fg="#ffffff")
            elif v == sobre and self.ativo:
                item.configure(bg=REALCE, fg=TEXTO)
            else:
                item.configure(bg=PAINEL2, fg=SUAVE if self.ativo else APAGADO)

    def ligar(self, sim: bool) -> None:
        self.ativo = sim
        for item in self.itens.values():
            item.configure(cursor="hand2" if sim else "arrow")
        self._pintar()


class Caixa(tk.Frame):
    """Caixa de marcar."""

    def __init__(self, mestre, texto: str, variavel: tk.BooleanVar,
                 ao_mudar: Optional[Callable] = None):
        super().__init__(mestre, bg=mestre["bg"], cursor="hand2")
        self.variavel = variavel
        self.ao_mudar = ao_mudar
        self.ativo = True
        lado = px(18)
        self.quadro = tk.Canvas(self, width=lado, height=lado, bg=self["bg"], highlightthickness=0)
        self.quadro.pack(side="left")
        self.texto = rotulo(self, texto, 10, TEXTO)
        self.texto.pack(side="left", padx=(px(8), 0))
        for w in (self, self.quadro, self.texto):
            w.bind("<Button-1>", self._alternar)
        self._pintar()

    def _alternar(self, _evento=None) -> None:
        if not self.ativo:
            return
        self.variavel.set(not self.variavel.get())
        self._pintar()
        if self.ao_mudar:
            self.ao_mudar()

    def _pintar(self) -> None:
        q, lado = self.quadro, px(18)
        q.delete("all")
        marcado = self.variavel.get()
        cor = (DESTAQUE if self.ativo else APAGADO) if marcado else PAINEL2
        q.create_rectangle(1, 1, lado - 1, lado - 1, fill=cor, outline=cor if marcado else BORDA)
        if marcado:
            q.create_line(lado * .24, lado * .52, lado * .43, lado * .70, lado * .77, lado * .30,
                          fill="#ffffff", width=px(2), capstyle="round", joinstyle="round")
        self.texto.configure(fg=TEXTO if self.ativo else APAGADO)

    def ligar(self, sim: bool) -> None:
        self.ativo = sim
        self.configure(cursor="hand2" if sim else "arrow")
        self._pintar()


class Deslizador(tk.Canvas):
    """Barra de posicao do video: clicar ou arrastar leva direto ao ponto."""

    def __init__(self, mestre, ao_mover: Callable[[float, bool], None]):
        super().__init__(mestre, height=px(22), bg=mestre["bg"], highlightthickness=0, cursor="hand2")
        self.ao_mover = ao_mover
        self.valor, self.maximo = 0.0, 1.0
        self.arrastando = False
        self.bind("<Configure>", lambda e: self._pintar())
        self.bind("<Button-1>", self._apertar)
        self.bind("<B1-Motion>", lambda e: self._mover(e, False))
        self.bind("<ButtonRelease-1>", self._soltar)

    def definir(self, valor: float, maximo: Optional[float] = None) -> None:
        if maximo is not None:
            self.maximo = max(1.0, float(maximo))
        if not self.arrastando:
            self.valor = min(max(0.0, float(valor)), self.maximo)
            self._pintar()

    def _apertar(self, e) -> None:
        self.arrastando = True
        self._mover(e, False)

    def _soltar(self, e) -> None:
        self._mover(e, True)
        self.arrastando = False

    def _mover(self, e, final: bool) -> None:
        margem = px(9)
        util = max(1, self.winfo_width() - 2 * margem)
        self.valor = min(max(0.0, (e.x - margem) / util), 1.0) * self.maximo
        self._pintar()
        self.ao_mover(self.valor, final)

    def _pintar(self) -> None:
        self.delete("all")
        margem, meio = px(9), self.winfo_height() // 2
        largura = max(1, self.winfo_width() - 2 * margem)
        x = margem + largura * self.valor / self.maximo
        self.create_line(margem, meio, margem + largura, meio, fill=PAINEL2, width=px(4), capstyle="round")
        self.create_line(margem, meio, x, meio, fill=DESTAQUE, width=px(4), capstyle="round")
        r = px(7)
        self.create_oval(x - r, meio - r, x + r, meio + r, fill="#ffffff", outline="")


class BarraProgresso(tk.Canvas):
    """Barra de progresso fina, de 0 a 1."""

    def __init__(self, mestre):
        super().__init__(mestre, height=px(8), bg=mestre["bg"], highlightthickness=0)
        self.fracao = 0.0
        self.bind("<Configure>", lambda e: self._pintar())

    def definir(self, fracao: float) -> None:
        self.fracao = min(max(0.0, fracao), 1.0)
        self._pintar()

    def _pintar(self) -> None:
        self.delete("all")
        altura = self.winfo_height()
        raio, meio = altura / 2, altura // 2
        fim = max(raio + 1, self.winfo_width() - raio)
        self.create_line(raio, meio, fim, meio, fill=PAINEL2, width=altura, capstyle="round")
        if self.fracao > 0:
            self.create_line(raio, meio, raio + (fim - raio) * self.fracao, meio, fill=DESTAQUE,
                             width=altura, capstyle="round")


class ListaRolavel(tk.Frame):
    """Area com rolagem; os itens vao dentro de `self.dentro`."""

    def __init__(self, mestre, altura: int):
        super().__init__(mestre, bg=PAINEL, highlightthickness=1, highlightbackground=BORDA)
        self.tela = tk.Canvas(self, bg=PAINEL, highlightthickness=0, height=altura)
        self.barra = ttk.Scrollbar(self, orient="vertical", command=self.tela.yview)
        self.dentro = tk.Frame(self.tela, bg=PAINEL)
        self._id = self.tela.create_window(0, 0, window=self.dentro, anchor="nw")
        self.tela.configure(yscrollcommand=self._rolou)
        self.tela.pack(side="left", fill="both", expand=True)
        self.dentro.bind("<Configure>", lambda e: self.tela.configure(scrollregion=self.tela.bbox("all")))
        self.tela.bind("<Configure>", lambda e: self.tela.itemconfigure(self._id, width=e.width))
        self.winfo_toplevel().bind("<MouseWheel>", self._roda, add="+")
        self._cabe = True

    def _rolou(self, inicio, fim) -> None:
        self._cabe = float(inicio) <= 0 and float(fim) >= 1
        if self._cabe:
            self.barra.pack_forget()
        elif not self.barra.winfo_ismapped():
            self.barra.pack(side="right", fill="y")
        self.barra.set(inicio, fim)

    def _roda(self, e) -> None:
        alvo = self.winfo_containing(e.x_root, e.y_root)
        if not self._cabe and alvo is not None and str(alvo).startswith(str(self)):
            self.tela.yview_scroll(-1 if e.delta > 0 else 1, "units")
