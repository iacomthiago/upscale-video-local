"""Nucleo do upscale: ffmpeg extrai os quadros, o Real-ESRGAN (Vulkan) amplia
na GPU e o ffmpeg remonta o video com o audio original.

Uso pela linha de comando:
    python upscaler.py video.mp4 [--altura 1080] [--modo rapido|realista_rapido|anime|realista]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Optional

RAIZ = Path(__file__).resolve().parent
PASTA_MOTOR = RAIZ / "motor"
EXE_MOTOR = PASTA_MOTOR / "realesrgan-ncnn-vulkan.exe"
URL_MOTOR = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
    "realesrgan-ncnn-vulkan-20220424-windows.zip"
)
SHA256_MOTOR = "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"

# Modelos que nao vem no pacote oficial: (arquivo, sha256). Baixados de uma versao fixa do
# repositorio upscayl/custom-models (conversoes para ncnn dos modelos oficiais do Real-ESRGAN).
URL_EXTRAS = ("https://raw.githubusercontent.com/upscayl/custom-models/"
              "4b6d2cfa59c7442af115dfc6e50fd8d7d40b96ef/models/")
MODELOS_EXTRAS = [
    ("RealESRGAN_General_x4_v3.bin", "85ee266b632a765a725425ba6a5620c088c8aa2939a03063b2d83b3462724cc1"),
    ("RealESRGAN_General_x4_v3.param", "22174924330297357434ad21ed0af7f4b820008d2a502b492754d130d4142714"),
]

# modo -> (modelo, escalas nativas disponiveis, quadros/s medidos numa RX 7600 em 480p)
MODOS = {
    "rapido": ("realesr-animevideov3", (2, 3, 4), 7.0),
    "realista_rapido": ("RealESRGAN_General_x4_v3", (4,), 4.5),
    "anime": ("realesrgan-x4plus-anime", (4,), 1.0),
    "realista": ("realesrgan-x4plus", (4,), 0.3),
}
NOMES_MODOS = {"rapido": "Rápido", "realista_rapido": "Realista rápido",
               "anime": "Anime detalhado", "realista": "Realista máximo"}
RESUMO_MODOS = {
    "rapido": "Anime e vídeo estilizado",
    "realista_rapido": "Imagem real, quase tão veloz quanto o Rápido",
    "anime": "Anime com traço mais limpo",
    "realista": "Imagem real no máximo de detalhe; bem lento",
}

QUADROS_POR_LOTE = 96
SEM_JANELA = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class Cancelado(Exception):
    pass


class ErroUpscale(Exception):
    pass


@dataclass
class InfoVideo:
    largura: int
    altura: int
    fps: Fraction
    duracao: float
    matriz_cor: str
    faixa_cor: str
    codec_audio: Optional[str]


@dataclass
class Progresso:
    etapa: str
    feitos: int = 0
    total: int = 0
    restante_s: Optional[float] = None


def _faltam_extras() -> list:
    return [(nome, sha) for nome, sha in MODELOS_EXTRAS if not (PASTA_MOTOR / "models" / nome).exists()]


def motor_instalado() -> bool:
    return EXE_MOTOR.exists() and (PASTA_MOTOR / "models").is_dir() and not _faltam_extras()


def _baixar(url: str, destino: Path, sha256: str, etapa: str,
            progresso: Optional[Callable[["Progresso"], None]]) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "upscale-video-local"})
    sha = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(destino, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            feitos = 0
            while True:
                bloco = resp.read(1 << 18)
                if not bloco:
                    break
                f.write(bloco)
                sha.update(bloco)
                feitos += len(bloco)
                if progresso:
                    progresso(Progresso(etapa, feitos, total))
        if sha.hexdigest() != sha256:
            raise ErroUpscale(f"O arquivo {destino.name} baixado não confere com o original. Tente de novo.")
    except BaseException:
        destino.unlink(missing_ok=True)
        raise


def instalar_motor(progresso: Optional[Callable[[Progresso], None]] = None) -> None:
    """Baixa o que faltar: o Real-ESRGAN oficial (cerca de 43 MB) e o modelo realista rapido (2 MB)."""
    PASTA_MOTOR.mkdir(exist_ok=True)
    if not EXE_MOTOR.exists():
        zip_path = PASTA_MOTOR / "motor.zip"
        try:
            _baixar(URL_MOTOR, zip_path, SHA256_MOTOR, "Baixando o motor de upscale", progresso)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(PASTA_MOTOR)
        finally:
            zip_path.unlink(missing_ok=True)
    for nome, sha in _faltam_extras():
        temporario = PASTA_MOTOR / "models" / (nome + ".baixando")
        _baixar(URL_EXTRAS + nome, temporario, sha, "Baixando o modelo realista rápido", progresso)
        os.replace(temporario, PASTA_MOTOR / "models" / nome)
    if not motor_instalado():
        raise ErroUpscale("O motor foi baixado, mas ficou incompleto na pasta 'motor'.")


def _ferramenta(nome: str) -> str:
    caminho = shutil.which(nome)
    if not caminho:
        raise ErroUpscale(
            f"Não encontrei o '{nome}'. Instale o FFmpeg (no PowerShell: winget install Gyan.FFmpeg) "
            "e abra o aplicativo de novo."
        )
    return caminho


def analisar(video: Path) -> InfoVideo:
    saida = subprocess.run(
        [_ferramenta("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=SEM_JANELA,
    )
    if saida.returncode != 0:
        raise ErroUpscale(f"Não consegui ler o vídeo: {saida.stderr.strip()[:300]}")
    dados = json.loads(saida.stdout)
    v = next((s for s in dados["streams"] if s.get("codec_type") == "video"), None)
    if v is None:
        raise ErroUpscale("Esse arquivo não tem faixa de vídeo.")
    a = next((s for s in dados["streams"] if s.get("codec_type") == "audio"), None)

    def taxa(texto: Optional[str]) -> Optional[Fraction]:
        try:
            f = Fraction(texto)
            return f if f > 0 else None
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    fps = taxa(v.get("avg_frame_rate")) or taxa(v.get("r_frame_rate")) or Fraction(24)
    largura, altura = int(v["width"]), int(v["height"])
    # Sem marcacao de cor, os players assumem BT.601 em SD e BT.709 em HD; faco o mesmo.
    matriz = v.get("color_space")
    if matriz not in ("bt709", "bt470bg", "smpte170m"):
        matriz = "bt709" if (largura >= 1280 or altura > 576) else "smpte170m"
    faixa = "pc" if v.get("color_range") == "pc" else "tv"
    return InfoVideo(
        largura=largura, altura=altura, fps=fps,
        duracao=float(dados.get("format", {}).get("duration") or 0),
        matriz_cor=matriz, faixa_cor=faixa,
        codec_audio=a.get("codec_name") if a else None,
    )


def estimar_segundos(modo: str, quadros: float, largura: int = 854, altura: int = 480) -> float:
    """Tempo aproximado de processamento, a partir da velocidade medida em 854x480."""
    return quadros * (largura * altura) / (854 * 480) / MODOS[modo][2]


def miniatura(video: Path, largura: int, altura: int, cor_fundo: str = "272a37") -> bytes:
    """Um quadro do video em PNG, ja no tamanho da miniatura."""
    saida = subprocess.run(
        [_ferramenta("ffmpeg"), "-v", "error", "-ss", "0.5", "-i", str(video), "-frames:v", "1",
         "-vf", (f"scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
                 f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2:color=0x{cor_fundo}"),
         "-f", "image2pipe", "-c:v", "png", "-"],
        capture_output=True, creationflags=SEM_JANELA,
    )
    return saida.stdout if saida.returncode == 0 else b""


def _tamanho_png(arquivo: Path) -> tuple[int, int]:
    with open(arquivo, "rb") as f:
        cabecalho = f.read(24)
    return struct.unpack(">II", cabecalho[16:24])


def _par(n: float) -> int:
    return max(2, int(round(n / 2)) * 2)


def calcular_saida(largura: int, altura: int, lado_menor: int) -> tuple[int, int]:
    """Resolucao final: o lado menor vira `lado_menor` (1080p = 1920x1080 ou 1080x1920)."""
    fator = lado_menor / min(largura, altura)
    maior = _par(max(largura, altura) * fator)
    # 854x480 e "quase 16:9": fecha em 1920x1080 exato em vez de 1922x1080.
    padrao = _par(lado_menor * 16 / 9)
    if abs(maior - padrao) <= 4:
        maior = padrao
    return (maior, _par(lado_menor)) if largura >= altura else (_par(lado_menor), maior)


def escolher_escala(modo: str, largura: int, altura: int, lado_menor: int) -> int:
    escalas = MODOS[modo][1]
    necessario = lado_menor / min(largura, altura)
    for e in escalas:
        if e >= necessario - 1e-6:
            return e
    return escalas[-1]


def nome_saida(video: Path, lado_menor: int, pasta: Optional[Path] = None, sufixo: str = "") -> Path:
    """Nome do arquivo final; nunca sobrescreve um arquivo que ja existe."""
    base = f"{video.stem}_{lado_menor}p{sufixo}"
    destino = (pasta or video.parent) / f"{base}.mp4"
    n = 2
    while destino.exists():
        destino = (pasta or video.parent) / f"{base}_{n}.mp4"
        n += 1
    return destino


def _encerrar(proc: Optional[subprocess.Popen]) -> None:
    if proc and proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def _fim_do_log(arquivo: Path, linhas: int = 6) -> str:
    try:
        texto = arquivo.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        return "\n".join(texto[-linhas:])
    except OSError:
        return ""


def ampliar(
    video: Path,
    destino: Path,
    lado_menor: int = 1080,
    modo: str = "rapido",
    progresso: Optional[Callable[[Progresso], None]] = None,
    cancelar: Optional[threading.Event] = None,
    limite_segundos: Optional[float] = None,
    manter_cores: bool = True,
) -> Path:
    """Amplia `video` e grava em `destino`. Devolve o caminho do arquivo final."""
    if modo not in MODOS:
        raise ErroUpscale(f"Modo desconhecido: {modo}")
    if not motor_instalado():
        raise ErroUpscale("O motor de upscale ainda não foi instalado.")
    ffmpeg = _ferramenta("ffmpeg")
    info = analisar(video)
    avisar = progresso or (lambda p: None)
    cancelar = cancelar or threading.Event()

    def checar():
        if cancelar.is_set():
            raise Cancelado()

    tmp = Path(tempfile.mkdtemp(prefix="upscale_"))
    quadros, lote_in, lote_out = tmp / "quadros", tmp / "lote_in", tmp / "lote_out"
    for p in (quadros, lote_in, lote_out):
        p.mkdir()
    parcial = destino.with_name(destino.stem + ".parcial.mp4")
    codificador: Optional[subprocess.Popen] = None
    motor: Optional[subprocess.Popen] = None
    log_cod = None
    try:
        # 1) Quadros originais em PNG (sem perda), com a cor convertida do jeito certo.
        avisar(Progresso("Separando os quadros do vídeo"))
        corte = ["-t", f"{limite_segundos}"] if limite_segundos else []
        cmd = [ffmpeg, "-v", "error", "-y", "-i", str(video), *corte, "-map", "0:v:0",
               "-vf", f"scale=in_color_matrix={info.matriz_cor}:in_range={info.faixa_cor}:flags=accurate_rnd+full_chroma_int,format=rgb24",
               "-fps_mode", "cfr", "-r", str(info.fps),
               str(quadros / "q_%07d.png")]
        with open(tmp / "extrair.log", "wb") as log:
            extrator = subprocess.Popen(cmd, stdout=log, stderr=log, creationflags=SEM_JANELA)
            while extrator.poll() is None:
                if cancelar.is_set():
                    _encerrar(extrator)
                    raise Cancelado()
                time.sleep(0.2)
        lista = sorted(quadros.glob("q_*.png"))
        if extrator.returncode != 0 or not lista:
            raise ErroUpscale("Falha ao separar os quadros:\n" + _fim_do_log(tmp / "extrair.log"))
        total = len(lista)
        larg, alt = _tamanho_png(lista[0])
        larg_final, alt_final = calcular_saida(larg, alt, lado_menor)
        escala = escolher_escala(modo, larg, alt, lado_menor)
        modelo = MODOS[modo][0]

        # 2) Codificador: recebe os quadros ampliados por um canal e ja grava o MP4 final.
        audio_out = []
        if info.codec_audio:
            copia = info.codec_audio in ("aac", "mp3", "ac3", "eac3")
            audio_out = ["-map", "1:a:0", "-c:a", *(["copy"] if copia else ["aac", "-b:a", "256k"])]
        tamanho = f"scale={larg_final}:{alt_final}:flags=lanczos+accurate_rnd+full_chroma_int"
        saida_cor = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
        if manter_cores:
            # Os modelos deslocam um pouco a cor. Aqui a cor "de longe" (baixa frequencia) volta
            # a ser a do original, e o detalhe fino continua sendo o do upscale:
            #   resultado = ampliado + borrado(original - ampliado)
            lp, ap = _par(larg_final / 8), _par(alt_final / 8)
            relogio = f"setpts=N/({info.fps})/TB"
            filtro = (
                f"[0:v]{relogio},{tamanho},format=gbrp,split[amp][amp2];"
                f"[amp2]scale={lp}:{ap}:flags=area[amp_p];"
                f"[1:v]fps={info.fps},{relogio},scale={lp}:{ap}:flags=area:"
                f"in_color_matrix={info.matriz_cor}:in_range={info.faixa_cor},format=gbrp[ori_p];"
                "[ori_p][amp_p]blend=all_mode=grainextract,gblur=sigma=2,"
                f"scale={larg_final}:{alt_final}:flags=bicubic[dif];"
                f"[amp][dif]blend=all_mode=grainmerge,{saida_cor}[v]"
            )
        else:
            filtro = f"[0:v]{tamanho},{saida_cor}[v]"
        cmd = [ffmpeg, "-v", "error", "-y",
               "-f", "image2pipe", "-framerate", str(info.fps), "-c:v", "png", "-i", "-",
               *corte, "-i", str(video),
               "-filter_complex", filtro, "-map", "[v]", *audio_out,
               "-c:v", "libx264", "-preset", "medium", "-crf", "16",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-color_range", "tv", "-movflags", "+faststart", "-shortest", str(parcial)]
        log_cod = open(tmp / "codificar.log", "wb")
        codificador = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log_cod, stderr=log_cod,
                                       creationflags=SEM_JANELA)

        # 3) Amplia em lotes, para o disco nunca guardar mais que um lote de quadros grandes.
        inicio = time.monotonic()
        feitos = 0
        etapa = f"Ampliando {larg}x{alt} → {larg_final}x{alt_final}"
        avisar(Progresso(etapa, 0, total))
        for i in range(0, total, QUADROS_POR_LOTE):
            checar()
            lote = lista[i:i + QUADROS_POR_LOTE]
            for q in lote:
                q.rename(lote_in / q.name)
            with open(tmp / "motor.log", "wb") as log:
                motor = subprocess.Popen(
                    [str(EXE_MOTOR), "-i", str(lote_in), "-o", str(lote_out),
                     "-n", modelo, "-s", str(escala), "-f", "png", "-j", "2:2:4"],
                    stdout=log, stderr=log, cwd=str(PASTA_MOTOR), creationflags=SEM_JANELA)
                while motor.poll() is None:
                    if cancelar.is_set():
                        _encerrar(motor)
                        raise Cancelado()
                    time.sleep(0.4)
                    prontos = feitos + sum(1 for _ in lote_out.iterdir())
                    decorrido = time.monotonic() - inicio
                    resta = decorrido / prontos * (total - prontos) if prontos else None
                    avisar(Progresso(etapa, min(prontos, total), total, resta))
            saidas = [lote_out / q.name for q in lote]
            if motor.returncode != 0 or not all(s.exists() for s in saidas):
                raise ErroUpscale("O motor de upscale falhou:\n" + _fim_do_log(tmp / "motor.log"))
            for q, s in zip(lote, saidas):
                checar()
                try:
                    codificador.stdin.write(s.read_bytes())
                except (BrokenPipeError, OSError):
                    raise ErroUpscale("Falha ao gravar o vídeo:\n" + _fim_do_log(tmp / "codificar.log"))
                s.unlink()
                (lote_in / q.name).unlink()
            feitos += len(lote)

        avisar(Progresso("Finalizando o arquivo", total, total, 0))
        codificador.stdin.close()
        codificador.wait()
        if codificador.returncode != 0 or not parcial.exists():
            raise ErroUpscale("Falha ao gravar o vídeo:\n" + _fim_do_log(tmp / "codificar.log"))
        os.replace(parcial, destino)
        return destino
    finally:
        _encerrar(motor)
        if codificador and codificador.poll() is None:
            try:
                codificador.stdin.close()
            except OSError:
                pass
            _encerrar(codificador)
        if log_cod:
            log_cod.close()
        parcial.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)


def formatar_tempo(segundos: Optional[float]) -> str:
    if segundos is None or math.isinf(segundos):
        return "calculando..."
    s = int(round(segundos))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Upscale de vídeo local com Real-ESRGAN")
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--altura", type=int, default=1080, help="lado menor final (padrão 1080)")
    ap.add_argument("--modo", choices=list(MODOS), default="rapido")
    ap.add_argument("--pasta", type=Path, help="pasta de saída (padrão: a mesma do vídeo)")
    ap.add_argument("--teste", type=float, metavar="SEG", help="processa só os primeiros SEG segundos")
    ap.add_argument("--sem-correcao-de-cor", action="store_true",
                    help="não devolve ao resultado as cores do vídeo original")
    args = ap.parse_args()
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    def mostrar(p: Progresso):
        if p.total:
            print(f"\r{p.etapa}: {p.feitos}/{p.total}  resta {formatar_tempo(p.restante_s)}   ",
                  end="", flush=True)
        else:
            print(p.etapa, flush=True)

    if not motor_instalado():
        instalar_motor(mostrar)
        print()
    for video in args.videos:
        destino = nome_saida(video, args.altura, args.pasta, "_teste" if args.teste else "")
        try:
            ampliar(video, destino, args.altura, args.modo, mostrar, limite_segundos=args.teste,
                    manter_cores=not args.sem_correcao_de_cor)
        except ErroUpscale as e:
            print(f"\nERRO em {video.name}: {e}")
            return 1
        print(f"\nPronto: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
