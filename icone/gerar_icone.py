"""Desenha o icone do aplicativo (play de video + brilho de IA) sem depender de bibliotecas.

Rode `python icone/gerar_icone.py` para recriar os PNGs e o .ico depois de mexer no desenho.
"""
import math
import struct
import zlib
from pathlib import Path

PASTA = Path(__file__).resolve().parent
TAMANHOS = (16, 32, 48, 256)

COR_CIMA = (166, 112, 255)     # violeta claro, canto de cima
COR_BAIXO = (84, 56, 232)      # violeta profundo, canto de baixo
COR_PLAY = (255, 255, 255)
COR_BRILHO = (255, 232, 160)

TRIANGULO = [(0.345, 0.335), (0.345, 0.735), (0.665, 0.535)]
RAIO_TRIANGULO = 0.045
BRILHOS = [(0.715, 0.275, 0.185), (0.845, 0.520, 0.075)]  # (x, y, raio)


def _fora_do_fundo(x: float, y: float) -> bool:
    meio, raio = 0.48, 0.225
    dx, dy = abs(x - 0.5) - (meio - raio), abs(y - 0.5) - (meio - raio)
    return math.hypot(max(dx, 0), max(dy, 0)) + min(max(dx, dy), 0) - raio > 0


def _dist_poligono(x: float, y: float, pontos: list) -> float:
    menor, dentro = float("inf"), False
    for i, (ax, ay) in enumerate(pontos):
        bx, by = pontos[(i + 1) % len(pontos)]
        ex, ey, wx, wy = bx - ax, by - ay, x - ax, y - ay
        t = max(0.0, min(1.0, (wx * ex + wy * ey) / (ex * ex + ey * ey)))
        menor = min(menor, math.hypot(wx - ex * t, wy - ey * t))
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            dentro = not dentro
    return -menor if dentro else menor


def _no_brilho(x: float, y: float) -> bool:
    for cx, cy, r in BRILHOS:
        dx, dy = abs(x - cx), abs(y - cy)
        if dx < r and dy < r and dx ** 0.56 + dy ** 0.56 < r ** 0.56:
            return True
    return False


def _amostra(x: float, y: float):
    if _fora_do_fundo(x, y):
        return None
    if _no_brilho(x, y):
        return COR_BRILHO
    if _dist_poligono(x, y, TRIANGULO) < RAIO_TRIANGULO:
        return COR_PLAY
    t = (x + y) / 2
    return tuple(a + (b - a) * t for a, b in zip(COR_CIMA, COR_BAIXO))


def desenhar(lado: int) -> bytes:
    """Devolve os pixels RGBA; cada pixel e a media de varias amostras (borda suave)."""
    sub = 4 if lado >= 128 else 8
    pixels = bytearray()
    for py in range(lado):
        for px in range(lado):
            r = g = b = cobertura = 0.0
            for sy in range(sub):
                for sx in range(sub):
                    cor = _amostra((px + (sx + 0.5) / sub) / lado, (py + (sy + 0.5) / sub) / lado)
                    if cor:
                        r, g, b, cobertura = r + cor[0], g + cor[1], b + cor[2], cobertura + 1
            if cobertura:
                pixels += bytes((round(r / cobertura), round(g / cobertura), round(b / cobertura),
                                 round(255 * cobertura / (sub * sub))))
            else:
                pixels += b"\0\0\0\0"
    return bytes(pixels)


def png(lado: int, rgba: bytes) -> bytes:
    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))
    linhas = b"".join(b"\0" + rgba[y * lado * 4:(y + 1) * lado * 4] for y in range(lado))
    return (b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 6, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(linhas, 9)) + bloco(b"IEND", b""))


def ico(imagens: dict) -> bytes:
    cabecalho = struct.pack("<HHH", 0, 1, len(imagens))
    posicao = 6 + 16 * len(imagens)
    entradas, corpo = b"", b""
    for lado, dados in imagens.items():
        entradas += struct.pack("<BBBBHHII", lado % 256, lado % 256, 0, 0, 1, 32, len(dados), posicao)
        corpo += dados
        posicao += len(dados)
    return cabecalho + entradas + corpo


if __name__ == "__main__":
    prontos = {}
    for lado in TAMANHOS:
        prontos[lado] = png(lado, desenhar(lado))
        (PASTA / f"icone_{lado}.png").write_bytes(prontos[lado])
        print(f"icone_{lado}.png")
    (PASTA / "icone.ico").write_bytes(ico(prontos))
    print("icone.ico")
