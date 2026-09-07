"""
Grafo de relacoes societarias (desafio extra opcional).

A partir de uma empresa, monta uma rede com:
  - a propria empresa (no central)
  - seus socios diretos
  - outras empresas onde esses mesmos socios tambem aparecem

Isso revela rapidamente redes de participacao societaria compartilhada.

O layout e calculado manualmente (nada de fisica/estabilizacao do vis.js):
a empresa central fica na origem, os socios em um circulo ao redor dela, e as
"outras empresas" de cada socio em um circulo menor ao redor do socio. Isso
evita que o grafo fique dependente de estabilizacao assincrona do lado do
navegador (que pode deixar os nos amontoados num canto ate a fisica convergir).
"""

from __future__ import annotations

import math

import pandas as pd
from pyvis.network import Network


def build_socio_network_html(
    cnpj_basico: str,
    razao_social: str,
    socios: pd.DataFrame,
    outras_empresas: pd.DataFrame,
    height: str = "520px",
) -> str:
    net = Network(height=height, width="100%", bgcolor="#111827", font_color="#f3f4f6", directed=False)
    net.toggle_physics(False)

    empresa_node = f"E:{cnpj_basico}"
    net.add_node(
        empresa_node,
        label=razao_social[:40],
        color="#f59e0b",
        size=32,
        title=razao_social,
        x=0,
        y=0,
        fixed=True,
    )

    n_socios = len(socios)
    raio_socios = 220
    for i, (_, socio) in enumerate(socios.iterrows()):
        angulo = 2 * math.pi * i / max(n_socios, 1)
        sx = raio_socios * math.cos(angulo)
        sy = raio_socios * math.sin(angulo)
        socio_node = f"S:{socio['cnpj_cpf_socio']}"
        net.add_node(
            socio_node,
            label=(socio["nome_socio"] or "")[:30],
            color="#60a5fa",
            size=20,
            title=socio["nome_socio"],
            x=sx,
            y=sy,
            fixed=True,
        )
        net.add_edge(empresa_node, socio_node)

        outras_do_socio = outras_empresas[outras_empresas["cnpj_cpf_socio"] == socio["cnpj_cpf_socio"]]
        n_outras = len(outras_do_socio)
        raio_outras = 120
        for j, (_, row) in enumerate(outras_do_socio.iterrows()):
            angulo_o = 2 * math.pi * j / max(n_outras, 1)
            ox = sx + raio_outras * math.cos(angulo_o)
            oy = sy + raio_outras * math.sin(angulo_o)
            outra_node = f"E:{row['cnpj_basico']}"
            net.add_node(
                outra_node,
                label=(row["razao_social"] or "")[:30],
                color="#34d399",
                size=14,
                title=row["razao_social"],
                x=ox,
                y=oy,
                fixed=True,
            )
            net.add_edge(socio_node, outra_node)

    net.set_options(
        """
        var options = {
          "physics": { "enabled": false },
          "edges": { "color": { "color": "#4b5563" }, "smooth": false },
          "interaction": { "dragNodes": false, "zoomView": true, "dragView": true }
        }
        """
    )
    html = net.generate_html(notebook=False)
    # Sem fisica, o vis.js nao dispara "stabilizationIterationsDone" (evento que o
    # template padrao do pyvis usa para centralizar a camera) - entao a visao fica
    # no zoom/posicao padrao em vez de enquadrar os nos. Precisamos chamar fit() na
    # mao. Como este grafo fica dentro de uma aba do Streamlit, o container pode
    # estar com display:none (tamanho zero) no momento em que o script roda -
    # por isso usamos ResizeObserver para so dar fit() quando o elemento realmente
    # tiver dimensao (aba visivel), com fallback de polling para navegadores sem
    # ResizeObserver ou caso a aba ja esteja visivel de inicio.
    fit_script = """
    <script>
    (function () {
        var el = document.getElementById('mynetwork');
        var fitted = false;
        function tryFit() {
            if (!fitted && el.clientWidth > 0 && el.clientHeight > 0) {
                network.fit();
                fitted = true;
            }
        }
        if (window.ResizeObserver) {
            new ResizeObserver(tryFit).observe(el);
        }
        var tries = 0;
        var iv = setInterval(function () {
            tries++;
            tryFit();
            if (fitted || tries > 25) clearInterval(iv);
        }, 200);
    })();
    </script>
    """
    html = html.replace("</body>", fit_script + "</body>")
    return html
