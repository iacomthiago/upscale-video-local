# Upscale de Vídeo Local

Aplicativo para Windows que amplia vídeos de 480p para 1080p (ou 720p / 1440p) direto na placa de vídeo do computador, sem custo por vídeo e sem enviar nada para a internet.

Feito para vídeos gerados por IA em baixa resolução: você gera em 480p, que é barato, e amplia aqui.

## Como usar

1. Dê dois cliques em `Iniciar.bat` (ou arraste os vídeos em cima dele).
2. Na primeira vez, o aplicativo pede para baixar o motor de upscale (≈ 43 MB). Aceite.
3. Clique em **Adicionar vídeos...**, escolha a resolução e a qualidade, e clique em **Começar**.

O resultado é salvo ao lado do original com o final `_1080p.mp4`. O original nunca é alterado nem sobrescrito. O áudio é mantido.

## Comparar antes de decidir

Cada vídeo da lista tem dois botões:

- **Testar qualidades** processa os 3 primeiros segundos nos três modos e abre a tela de comparação. Ela abre assim que o modo Rápido fica pronto; os outros dois entram sozinhos quando terminam.
- **Antes e depois** aparece quando o vídeo já tem algum resultado e abre a mesma tela com o original e o que foi gerado.

Na tela de comparação os dois lados tocam em sincronia, quadro a quadro. Você escolhe o que vai em cada lado (Original, Rápido, Anime detalhado, Realista), pausa com a barra de espaço, anda um quadro por vez com as setas e usa o zoom (100%, 200%, 400%) para enxergar a nitidez de perto, arrastando a imagem para olhar outra parte. O original aparece esticado até o tamanho do resultado, como um player faria. O botão **Usar ...** marca a qualidade escolhida na janela principal.

A comparação não toca o áudio.

## Modos de qualidade

Tempos medidos em uma Radeon RX 7600, vídeo 480p a 24 quadros por segundo:

| Modo | Para quê | Clipe de 10 s leva |
|---|---|---|
| Rápido | Uso geral, anime e estilizado | ≈ 40 s |
| Anime detalhado | Anime com traço mais limpo | ≈ 4 min |
| Realista | Pele, tecido, cenário real | ≈ 13 min |

## O que precisa ter instalado

- Windows 10 ou 11 com placa de vídeo com suporte a Vulkan (AMD, NVIDIA ou Intel, com driver atualizado)
- [Python 3.9 ou mais novo](https://www.python.org/downloads/)
- FFmpeg, que se instala com este comando no PowerShell:

```powershell
winget install Gyan.FFmpeg
```

Não há bibliotecas Python para instalar.

## Linha de comando

```powershell
python upscaler.py video.mp4 --altura 1080 --modo rapido
```

Opções: `--altura 720|1080|1440`, `--modo rapido|anime|realista`, `--pasta PASTA`, `--teste SEGUNDOS`.

## Como funciona

1. O FFmpeg separa o vídeo em quadros PNG, sem perda.
2. O [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (versão ncnn/Vulkan) amplia cada quadro na GPU, em lotes de 96 quadros para não lotar o disco.
3. O FFmpeg ajusta para a resolução exata e grava um MP4 H.264 de alta qualidade (CRF 16) com o áudio original.

Arquivos: `upscaler.py` faz o processamento, `app.py` é a janela principal, `comparar.py` é a tela de comparação e `tema.py` guarda as cores e os componentes visuais.

O motor Real-ESRGAN é baixado da página oficial do projeto e fica na pasta `motor/`, que não faz parte deste repositório. Ele é distribuído pelos autores sob licença BSD de 3 cláusulas.

## Limites

- Upscale melhora nitidez e contorno, mas não inventa detalhe que o vídeo original não tem. Um 480p ampliado fica bem melhor que o 480p esticado, e ainda um pouco abaixo de um vídeo gerado nativamente em 1080p.
- A ampliação é quadro a quadro. Em cenas com muito ruído ou textura fina pode aparecer uma leve cintilação, mais no modo Realista.
