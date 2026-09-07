"""
Grafo de relacoes societarias (desafio extra opcional).

A partir de uma empresa, monta uma rede com:
  - a propria empresa (no central, no topo)
  - seus socios diretos (uma fileira abaixo)
  - outras empresas onde esses mesmos socios tambem aparecem (fileira seguinte)

Isso revela rapidamente redes de participacao societaria compartilhada.

O layout e uma arvore hierarquica calculada a mao (nada de fisica/estabilizacao
do vis.js, nem layouts de forca genericos tipo spring/kamada-kawai). Um grafo
"estrela" - varios socios ligados apenas a empresa, sem ligacao entre si - e
exatamente o caso em que layouts de forca degeneram: com 2 socios, por
exemplo, o equilibrio de forcas sempre os empurra para lados opostos do
centro, ficando colineares (alinhados) e, dependendo da escala, colados nas
bordas do canvas. Como a estrutura aqui e sempre a mesma (empresa -> socios
-> outras empresas), um layout em arvore evita esse caso especial: cada nivel
fica numa fileira, e a largura de cada "galho" e calculada a partir de quantos
nos ele contem, garantindo espacamento minimo sem sobreposicao.
"""

from __future__ import annotations

import pandas as pd
from pyvis.network import Network

COR_EMPRESA = "#f59e0b"
COR_SOCIO = "#60a5fa"
COR_OUTRA_EMPRESA = "#34d399"

ESPACO_SOCIO = 220  # espaco horizontal minimo entre dois socios (ou entre seus galhos)
ESPACO_OUTRA = 150  # espaco horizontal entre "outras empresas" de um mesmo socio
ESPACO_ENTRE_GALHOS = 60
ALTURA_NIVEL = 220  # distancia vertical entre empresa -> socios -> outras empresas


def build_socio_network_html(
    cnpj_basico: str,
    razao_social: str,
    socios: pd.DataFrame,
    outras_empresas: pd.DataFrame,
    height: str = "560px",
) -> str:
    net = Network(height=height, width="100%", bgcolor="#111827", font_color="#f3f4f6", directed=False)
    net.toggle_physics(False)

    empresa_node = f"E:{cnpj_basico}"

    # 1) calcula a largura do "galho" de cada socio (baseada em quantas outras
    #    empresas ele tem) e posiciona os socios lado a lado sem sobrepor.
    galhos = []
    for _, socio in socios.iterrows():
        outras_do_socio = outras_empresas[outras_empresas["cnpj_cpf_socio"] == socio["cnpj_cpf_socio"]]
        n_outras = len(outras_do_socio)
        largura_galho = max(ESPACO_SOCIO, n_outras * ESPACO_OUTRA)
        galhos.append({"socio": socio, "outras": outras_do_socio, "largura": largura_galho})

    largura_total = sum(g["largura"] for g in galhos) + ESPACO_ENTRE_GALHOS * max(len(galhos) - 1, 0)
    cursor_x = -largura_total / 2

    net.add_node(
        empresa_node,
        label=razao_social[:40],
        title=razao_social,
        color=COR_EMPRESA,
        size=32,
        x=0,
        y=0,
        fixed=True,
    )

    for galho in galhos:
        socio = galho["socio"]
        centro_x = cursor_x + galho["largura"] / 2
        cursor_x += galho["largura"] + ESPACO_ENTRE_GALHOS

        socio_node = f"S:{socio['cnpj_cpf_socio']}"
        net.add_node(
            socio_node,
            label=(socio["nome_socio"] or "")[:30],
            title=socio["nome_socio"],
            color=COR_SOCIO,
            size=20,
            x=centro_x,
            y=ALTURA_NIVEL,
            fixed=True,
        )
        net.add_edge(empresa_node, socio_node)

        outras_do_socio = galho["outras"]
        n_outras = len(outras_do_socio)
        if n_outras:
            inicio_outras = centro_x - (n_outras - 1) * ESPACO_OUTRA / 2
            for j, (_, row) in enumerate(outras_do_socio.iterrows()):
                outra_node = f"E:{row['cnpj_basico']}"
                net.add_node(
                    outra_node,
                    label=(row["razao_social"] or "")[:30],
                    title=row["razao_social"],
                    color=COR_OUTRA_EMPRESA,
                    size=14,
                    x=inicio_outras + j * ESPACO_OUTRA,
                    y=ALTURA_NIVEL * 2,
                    fixed=True,
                )
                net.add_edge(socio_node, outra_node)

    net.set_options(
        """
        var options = {
          "physics": { "enabled": false },
          "edges": { "color": { "color": "#4b5563" }, "smooth": false },
          "interaction": { "dragNodes": false, "zoomView": true, "dragView": true, "hover": true }
        }
        """
    )

    tem_outras = any(len(g["outras"]) for g in galhos)
    margem = 90
    conteudo_largura = largura_total + margem * 2
    conteudo_altura = (ALTURA_NIVEL * (2 if tem_outras else 1) if galhos else 0) + margem * 2
    centro_x = 0  # a arvore ja e construida centralizada em x=0
    centro_y = (ALTURA_NIVEL * (2 if tem_outras else 1) if galhos else 0) / 2

    html = net.generate_html(notebook=False)
    # Sem fisica, o vis.js nao dispara "stabilizationIterationsDone" (evento que o
    # template padrao do pyvis usa para centralizar a camera), entao a visao fica
    # no zoom/posicao padrao em vez de enquadrar os nos. O metodo obvio seria
    # chamar network.fit(), mas na pratica ele calcula um zoom incorreto aqui
    # (chega a encolher a escala para ~0.5 mesmo com poucos nos, deixando tudo
    # amontoado num canto) - possivelmente por rodar antes do layout do
    # container/CSS do Streamlit estabilizar de vez. Como ja sabemos exatamente
    # a caixa delimitadora dos nos (nos mesmos calculamos o layout em arvore em
    # Python), enquadramos a camera na mao com moveTo() usando essas medidas,
    # sem depender da heuristica do fit(). O ResizeObserver + polling continuam
    # necessarios so para esperar a aba ficar visivel (tamanho > 0) antes de
    # aplicar o enquadramento.
    fit_script = f"""
    <script>
    (function () {{
        var el = document.getElementById('mynetwork');
        var fitted = false;
        function tryFit() {{
            if (!fitted && el.clientWidth > 0 && el.clientHeight > 0) {{
                var escala = Math.min(el.clientWidth / {conteudo_largura}, el.clientHeight / {conteudo_altura});
                escala = Math.max(0.3, Math.min(escala, 1.3));
                network.moveTo({{position: {{x: {centro_x}, y: {centro_y}}}, scale: escala, animation: false}});
                fitted = true;
            }}
        }}
        if (window.ResizeObserver) {{
            new ResizeObserver(tryFit).observe(el);
        }}
        var tries = 0;
        var iv = setInterval(function () {{
            tries++;
            tryFit();
            if (fitted || tries > 25) clearInterval(iv);
        }}, 200);
    }})();
    </script>
    """
    # Clique em um no de empresa (a central, cor laranja, ou uma das "outras
    # empresas", cor verde) deve abrir a ficha daquela empresa no app. Um
    # componente via components.html roda num iframe sandboxed sem permissao
    # de navegacao (window.parent.location = ... e bloqueado com SecurityError
    # pelo navegador - testado). Como o iframe tem "allow-same-origin", ele
    # consegue mexer no DOM da pagina pai normalmente; entao em vez de navegar,
    # localizamos e "clicamos" via JS num botao comum do Streamlit (renderizado
    # oculto em app.py, um por empresa do grafo) que corresponde a empresa
    # clicada. Um clique real em <button> passa pelo pipeline normal de
    # eventos do React, ao contrario de tentar simular digitação num input.
    click_script = """
    <script>
    (function () {
        function clicarBotaoDaEmpresa(cnpj) {
            var alvo = "abrir_empresa_" + cnpj;
            var botoes = window.parent.document.querySelectorAll("button");
            for (var i = 0; i < botoes.length; i++) {
                if (botoes[i].textContent.trim() === alvo) {
                    botoes[i].click();
                    return;
                }
            }
        }
        network.on("click", function (params) {
            if (params.nodes.length === 0) return;
            var nodeId = params.nodes[0];
            if (nodeId.indexOf("E:") !== 0) return;
            clicarBotaoDaEmpresa(nodeId.substring(2));
        });
        network.on("hoverNode", function (params) {
            if (params.node.indexOf("E:") === 0) {
                document.body.style.cursor = "pointer";
            }
        });
        network.on("blurNode", function () {
            document.body.style.cursor = "default";
        });
    })();
    </script>
    """
    html = html.replace("</body>", fit_script + click_script + "</body>")
    return html
