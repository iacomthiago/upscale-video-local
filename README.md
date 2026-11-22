<img src="icone/icone_256.png" width="96" alt="Ícone do Upscale de Vídeo">

# Upscale de Vídeo Local

Por [@iacomthiago](https://github.com/iacomthiago)

Aplicativo para Windows que amplia vídeos de 480p para 1080p (ou 720p / 1440p) direto na placa de vídeo do computador, sem custo por vídeo e sem enviar nada para a internet.

Feito para vídeos gerados por IA em baixa resolução: você gera em 480p, que é barato, e amplia aqui.

## Como usar

1. Dê dois cliques em `Iniciar.bat` (ou arraste os vídeos em cima dele).
2. Na primeira vez, o aplicativo pede para baixar o motor de upscale e os modelos (≈ 46 MB). Aceite.
3. Clique em **Adicionar vídeos**, escolha a resolução e a qualidade, e clique em **Começar**.

O resultado é salvo ao lado do original com o final `_1080p.mp4`. O original nunca é alterado nem sobrescrito. O áudio é mantido.

## Modos de qualidade

Tempos medidos em uma Radeon RX 7600, vídeo 480p a 24 quadros por segundo:

| Modo | Para quê | Clipe de 10 s | Vídeo de 1 min |
|---|---|---|---|
| Rápido | Anime e vídeo estilizado | ≈ 35 s | ≈ 3,5 min |
| Realista rápido | Imagem real (pele, tecido, cenário), com o melhor custo-benefício | ≈ 55 s | ≈ 5,5 min |
| Anime detalhado | Anime com traço mais limpo | ≈ 4 min | ≈ 24 min |
| Realista máximo | Imagem real no máximo de detalhe | ≈ 13 min | ≈ 80 min |

O **Realista máximo** usa um modelo dezenas de vezes mais pesado; a velocidade dele é limitada pela placa de vídeo. O **Realista rápido** é da mesma família, numa versão compacta, e costuma ser a melhor escolha para vídeos longos.

## Cores iguais às do original

Os modelos de upscale deslocam um pouco a cor (clareiam, puxam para o azul). Com a opção **Manter as cores do vídeo original** ligada, que é o padrão, o aplicativo devolve ao resultado as cores do original e mantém só o ganho de nitidez. Nos testes, a diferença de cor para o original caiu de 2 a 4 pontos (em 255) para no máximo 1.

## Comparar antes de decidir

Cada vídeo da lista tem dois botões:

- **Testar qualidades** processa os 3 primeiros segundos em todos os modos e abre a tela de comparação. Ela abre assim que o modo Rápido fica pronto; os outros entram sozinhos quando terminam.
- **Antes e depois** aparece quando o vídeo já tem algum resultado e abre a mesma tela com o original e o que foi gerado.

Na tela de comparação os dois lados tocam em sincronia, quadro a quadro. Você escolhe o que vai em cada lado, pausa com a barra de espaço, anda um quadro por vez com as setas e usa o zoom (100%, 200%, 400%) para enxergar a nitidez de perto, arrastando a imagem para olhar outra parte. O original aparece esticado até o tamanho do resultado, como um player faria. O botão **Usar ...** marca a qualidade escolhida na janela principal.

A comparação não toca o áudio.

Dica: a caixa **Teste** processa só os 3 primeiros segundos de cada vídeo da lista no modo escolhido.

## Atualizações

Ao abrir, o aplicativo confere no GitHub se saiu versão nova. Se saiu, aparece um aviso no topo com o botão **Ver novidades e atualizar**: ele mostra o que mudou, baixa a versão nova, instala por cima e reabre o aplicativo. O motor e os modelos já baixados são mantidos. A checagem só lê o arquivo `VERSAO.txt` do repositório; nada do seu computador é enviado.

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
python upscaler.py video.mp4 --altura 1080 --modo realista_rapido
```

Opções: `--altura 720|1080|1440`, `--modo rapido|realista_rapido|anime|realista`, `--pasta PASTA`, `--teste SEGUNDOS`, `--sem-correcao-de-cor`.

## Como funciona

1. O FFmpeg separa o vídeo em quadros PNG, sem perda.
2. O [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (versão ncnn/Vulkan) amplia cada quadro na GPU, em lotes de 96 quadros para não lotar o disco.
3. O FFmpeg ajusta para a resolução exata, devolve as cores do original e grava um MP4 H.264 de alta qualidade (CRF 16) com o áudio original.

Arquivos: `upscaler.py` faz o processamento, `app.py` é a janela principal, `comparar.py` é a tela de comparação, `tema.py` guarda as cores e os componentes visuais, `atualizar.py` cuida do aviso de versão nova e `icone/` tem o ícone e o script que o desenha.

## Créditos dos componentes baixados

Ficam na pasta `motor/`, que não faz parte deste repositório:

- Motor e modelos do [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN), baixados da página oficial do projeto (licença BSD de 3 cláusulas).
- Modelo `RealESRGAN_General_x4_v3` (modo Realista rápido), do mesmo projeto, na conversão para ncnn publicada em [upscayl/custom-models](https://github.com/upscayl/custom-models).

O aplicativo confere a integridade (SHA-256) de cada arquivo baixado.

## Limites

- Upscale melhora nitidez e contorno, mas não inventa detalhe que o vídeo original não tem. Um 480p ampliado fica bem melhor que o 480p esticado, e ainda um pouco abaixo de um vídeo gerado nativamente em 1080p. Pelo mesmo motivo, ampliar um 480p até 4K não traz ganho visível sobre 1080p.
- A ampliação é quadro a quadro. Em cenas com muito ruído ou textura fina pode aparecer uma leve cintilação, mais nos modos realistas.
- Durante o processamento a placa de vídeo trabalha a 100%, como em um jogo pesado. É uso normal, mas o computador fica mais lento para outras tarefas.
