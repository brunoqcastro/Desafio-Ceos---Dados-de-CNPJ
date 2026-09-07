"""
Tabelas de dominio fixas do layout do CNPJ que a Receita NAO distribui como
arquivo separado (estao documentadas apenas no layout oficial em PDF).
"""

SITUACAO_CADASTRAL = {
    "01": "Nula",
    "02": "Ativa",
    "03": "Suspensa",
    "04": "Inapta",
    "08": "Baixada",
}

IDENTIFICADOR_MATRIZ_FILIAL = {
    "1": "Matriz",
    "2": "Filial",
}

IDENTIFICADOR_SOCIO = {
    "1": "Pessoa Juridica",
    "2": "Pessoa Fisica",
    "3": "Estrangeiro",
}

PORTE_EMPRESA = {
    "00": "Nao informado",
    "01": "Micro Empresa",
    "03": "Empresa de Pequeno Porte",
    "05": "Demais",
}

FAIXA_ETARIA = {
    "0": "Nao se aplica",
    "1": "0 a 12 anos",
    "2": "13 a 20 anos",
    "3": "21 a 30 anos",
    "4": "31 a 40 anos",
    "5": "41 a 50 anos",
    "6": "51 a 60 anos",
    "7": "61 a 70 anos",
    "8": "71 a 80 anos",
    "9": "Maior que 80 anos",
}
