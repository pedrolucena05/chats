import re

test = '''Para participar, é necessário passar por uma curadoria. Basta preencher o formulário disponível neste link: [formulário de curadoria da feira](https://docs.google.com/forms/d/e/1FAIpQLSdWUJJ14jH7k78t6tRx0_wqPHyGbwgAQ9_Hls7ziEmz3XBy3w/viewform?usp=pp_url). O valor da edição avulsa é de R$150,00. Existe também a opção de contrato anual com valor diferenciado para expositores fixos. As vagas dependem da aprovação na curadoria e disponibilidade no segmento desejado. Se precisar de mais alguma informação, fico à disposição!'''

link = ""
isLink = False

print(f"Antes do tratamento: {test}\n\n\n")
# Remove os colchetes da string de resposta (desnecessários e poluem a resposta)
cleanOutput = re.sub(r"\[.*?\]", "", test)

print(f"Depois do tratamento de colchetes: {cleanOutput}\n\n\n")
# Verifica se existe https coloca todo link numa variavel e remove da string caso exista link
if "https" in cleanOutput:
    match = re.search(r"https?://[^\s)\]\n]+", cleanOutput)
    if match:
        link = match.group().rstrip('.,!?;:')  # remove pontuação final solta
        print(f"Valor de link: {link}\n\n\n")
        isLink = True

        cleanOutput = re.sub(re.escape(link), "", cleanOutput, count=1)
        print(f"Apos retirar o link: {cleanOutput}\n\n\n")

aux = cleanOutput.split('.')
output = ""
cont = 0
if len(aux) >= 2:

    for item in aux:

        if cont%2 == 0:
            output += aux[cont] + "."
        else:
            output += aux[cont] + ".\n\n"
        cont += 1

elif len(aux) <= 1:
    output = aux[0] + "."

if isLink:
    parts = cleanOutput.split(":", 1)
    output = parts[0] + ": " + link + parts[1] #adiciona o link na saida caso exista

output = re.sub(r'\.(\s*)\.$', r'.\1', output)

output = output.replace("()", "")

print(f"Saidafinal: {output}")