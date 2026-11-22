"""Confere no GitHub se saiu versao nova do aplicativo e, se a pessoa pedir, instala.

A versao fica no arquivo VERSAO.txt: a primeira linha e o numero, as seguintes dizem
o que mudou. A checagem so le esse arquivo; nada do computador e enviado.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

REPO = "iacomthiago/upscale-video-local"
RAMO = "main"
RAIZ = Path(__file__).resolve().parent
ARQUIVO_VERSAO = "VERSAO.txt"
OBRIGATORIOS = ("app.py", "upscaler.py", ARQUIVO_VERSAO)


class ErroAtualizacao(Exception):
    pass


def _ler(texto: str) -> tuple[str, list[str]]:
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    return (linhas[0], linhas[1:]) if linhas else ("0", [])


def _numeros(versao: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", versao))


def _abrir(url: str, espera: float):
    pedido = urllib.request.Request(url, headers={"User-Agent": "upscale-video-local"})
    return urllib.request.urlopen(pedido, timeout=espera)


def versao_local() -> str:
    try:
        return _ler((RAIZ / ARQUIVO_VERSAO).read_text(encoding="utf-8"))[0]
    except OSError:
        return "0"


def copia_de_desenvolvimento() -> bool:
    """Pasta com Git e onde o aplicativo e editado: atualiza-se por la, nunca por cima."""
    return (RAIZ / ".git").exists()


def consultar(espera: float = 6) -> Optional[tuple[str, list[str]]]:
    """Devolve (versao, novidades) se o GitHub tiver versao mais nova; senao None."""
    try:
        url = f"https://raw.githubusercontent.com/{REPO}/{RAMO}/{ARQUIVO_VERSAO}"
        with _abrir(url, espera) as resposta:
            versao, novidades = _ler(resposta.read(20_000).decode("utf-8", "replace"))
    except (OSError, ValueError):  # sem internet, GitHub fora do ar...
        return None
    return (versao, novidades) if _numeros(versao) > _numeros(versao_local()) else None


def instalar(progresso: Optional[Callable[[int], None]] = None) -> str:
    """Baixa a versao mais nova e copia por cima desta. Devolve o numero da versao instalada.

    A pasta `motor/` nao faz parte do pacote, entao o motor e os modelos ficam como estao.
    """
    if copia_de_desenvolvimento():
        raise ErroAtualizacao("Esta pasta é a de desenvolvimento (tem Git). Atualize por lá.")
    tmp = Path(tempfile.mkdtemp(prefix="upscale_atualizar_"))
    try:
        pacote = tmp / "pacote.zip"
        try:
            url = f"https://github.com/{REPO}/archive/refs/heads/{RAMO}.zip"
            with _abrir(url, 30) as resposta, open(pacote, "wb") as f:
                baixados = 0
                while True:
                    bloco = resposta.read(1 << 16)
                    if not bloco:
                        break
                    f.write(bloco)
                    baixados += len(bloco)
                    if progresso:
                        progresso(baixados)
            with zipfile.ZipFile(pacote) as z:
                z.extractall(tmp / "novo")
        except (OSError, zipfile.BadZipFile) as e:
            raise ErroAtualizacao(f"Não consegui baixar a atualização: {e}")

        pastas = [p for p in (tmp / "novo").iterdir() if p.is_dir()]
        if len(pastas) != 1 or not all((pastas[0] / nome).is_file() for nome in OBRIGATORIOS):
            raise ErroAtualizacao("O pacote baixado veio incompleto. Nada foi alterado.")
        origem = pastas[0]
        # So instala se todo o codigo novo for valido; um download quebrado nao estraga o que funciona.
        for codigo in origem.rglob("*.py"):
            try:
                compile(codigo.read_text(encoding="utf-8"), str(codigo), "exec")
            except (SyntaxError, UnicodeDecodeError):
                raise ErroAtualizacao("O pacote baixado veio com defeito. Nada foi alterado.")

        for arquivo in origem.rglob("*"):
            if arquivo.is_file():
                destino = RAIZ / arquivo.relative_to(origem)
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(arquivo, destino)
        return versao_local()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def reiniciar() -> None:
    """Abre o aplicativo de novo, ja na versao instalada."""
    subprocess.Popen([sys.executable, str(RAIZ / "app.py")], cwd=str(RAIZ))
