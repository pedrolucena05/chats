import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

vs = client.vector_stores.create(name="FAQ - Perguntas e Respostas")
vector_store_id = vs.id
print("vector_store_id:", vector_store_id)

PALAVRAS_PEDIDO_INFO = [
    "qual",
    "quais",
    "poderia informar",
    "pode informar",
    "para qual",
    "qual feira",
    "qual dia",
    "qual segmento",
    "preciso saber",
    "poderia especificar",
    "informe",
    "especifique",
    "poderia dizer",
]

PALAVRAS_ATENDENTE = [
    "um atendente irá responder",
    "um atendente vai responder",
    "atendente irá responder",
    "atendente vai responder",
    "um atendente entrará em contato",
    "entraremos em contato",
    "nossa equipe irá responder",
    "nossa equipe vai responder",
    "iremos analisar",
    "vamos analisar",
    "sua dúvida será analisada",
    "encaminharemos sua dúvida",
]

file = client.files.create(
    file=open("perguntas_respostas.md", "rb"),
    purpose="assistants",
)

client.vector_stores.files.create(
    vector_store_id=vector_store_id,
    file_id=file.id,
)

SYSTEM_PROMPT = """
Você é um atendente das feiras.
Responda APENAS com base nas informações encontradas no documento fornecido.
Se não houver informação suficiente no documento, diga que não encontrou (e que um atendente irá analisar e responder a pergunta) ou peça um detalhe que faltou (ex.: qual feira/dia/segmento). 
Não invente valores, horários, locais ou regras. Responda de forma simpática.
Não mencione as feiras que trabalhamos na resposta (espere o usuario responder).
"""

def precisa_info(texto: str) -> bool:
    texto_lower = texto.lower()
    return any(p in texto_lower for p in PALAVRAS_PEDIDO_INFO)

def precisa_humano(texto: str) -> bool:
    texto_lower = texto.lower()

    return any(p in texto_lower for p in PALAVRAS_ATENDENTE)

def respClient(pergunta, msgs):
    status = None
    respMan = None

    question = ""
    if msgs:
        for m in msgs:
            question += " " + m

    question += " " + pergunta
    resp = client.responses.create(
        model="gpt-4.1",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        tools=[{
            "type": "file_search",
            "vector_store_ids": [vector_store_id],  # ✅ aqui é o correto
            "max_num_results": 6,
        }],
        include=["file_search_call.results"],
    )
    
    if "?" in resp.output_text:
        status = False
    
    else:
        status = not precisa_info(resp.output_text)

    if precisa_humano(resp.output_text):
        respMan = 1
    else:
        respMan = 0

    return resp.output_text, status, respMan

"""def respClient(original_msg, respMan, resps_order):

    message = None

    original_msg = str(original_msg)

    lower_msg = original_msg.lower()
    lower_msg = lower_msg.replace(' ', '')
    lower_msg = lower_msg.replace('\n', '')


    if resps_order == 0 or lower_msg == 'voltar' or lower_msg == 'volta' or (respMan == 0 and resps_order == 3 and (lower_msg == 'n' or lower_msg == 'sim')):

        message = f'''Olá! Seja bem vindo(a) ao atendimento da Feira do Lindu e Festival de Sabores de Apipucos.    
                    
Meu nome é Mayara e gostaria de saber qual opção abaixo voçê deseja:
                
            1 - Feira do Lindu (Domingos);
            2 - Feira Apipucos (Sábados);
            3 - Feira da Aurora (Sábados e Domingos);
            4 - Feira Bom Jesus (Domingos);
            5 - Dúvidas frequentes;
        
Digite o número da opção desejada:'''
        resps_order = 1
    
    elif resps_order == 1 or (respMan == 0 and  's' == lower_msg and resps_order == 3):
        
        if lower_msg in ['1', 'lindu']:
            message = '''A Feira do Lindu acontece aos domingos das 15:00h às 21:00h.
                        
Informações importantes:

Quanto custa expor seu trabalho no festival?
    
    - Será cobrada uma taxa de 10% sobre as vendas realizadas;
    - As maquinetas de cartão serão disponibilizadas pela organização do evento; 
    - Para confirmar sua participação, é necessário realizar o pagamento antecipado de R$150 — esse valor será abatido do total das suas vendas durante o festival.
    - Haverá o custo adicional de R$10 (taxa de uso do sistema de gerenciamento de vendas - Control Bar)+R$12,50 (taxa de aluguel da maquineta Stone);  
    ...
Você tem interesse em participar? responda com 'S' para sim ou 'N' para não. Ou digite 'voltar' para voltar para o menu inicial.'''
            resps_order = 2
            respMan = 0
        
        elif lower_msg in ['2', 'apipucos']:
            message = '''A Feira de Apipucos acontece aos sábados das 12:00h às 21:00h.

Informações importantes:

    - Será cobrada uma taxa de 10% sobre as vendas realizadas;
    - As maquinetas de cartão serão disponibilizadas pela organização do evento; 
    - Para confirmar sua participação, é necessário realizar o pagamento antecipado de R$180 — esse valor será abatido do total das suas vendas durante o festival.

Você tem interesse em participar? responda com 'S' para sim ou 'N' para não. Ou digite 'voltar' para voltar para o menu inicial.'''
            resps_order = 2
            respMan = 1

        
        elif lower_msg in ['3', 'aurora']:
            message = '''Esse número é apenas para a Feira do Lindu e Apipucos, segue o contato da administração da Feira da Aurora:
                        
https://w.app/nau7ub'''
            resps_order = 0
            respMan = 0

        elif lower_msg in ['4', 'jesus']:   
            message = '''Esse número é apenas para a Feira do Lindu e Apipucos, segue o contato da administração da Feira da Bom Jesus:
                        
https://w.app/g6v50y'''
            resps_order = 0
            respMan = 0
        
        elif lower_msg in ['5' , 'duvidas', 'frequentes'] or (respMan == 0 and  's' == lower_msg and resps_order == 3) :
            message = '''Qual sua dúvida?
            
    1 - Como faço para participar da Feira? 
    2 - Qual é a taxa de participação? esse valor é cobrado mensalmente?
    3 - Quais dias e horários a Feira do Lindu e o Festival de Sabores Apipucos Acontecem?
    4 - O que está incluso no valor de participação?
    5 - Posso escolher a localização do meu espaço na feira?
    6 - Posso levar mesas, araras ou estantes próprias?
    7 - Tem vaga para o meu segmento?
    0 - Tenho outra dúvida.

Digite o número da dúvida desejada, ou digite 'Voltar' para voltar para o menu principal:'''
            resps_order = 2
            respMan = 2

        else:
            message = '''Não entendi! 
                        
Digite o número da opção desejada: '''
            
    elif resps_order == 2 or (resps_order == 3 and respMan == 0 and  's' == lower_msg):

            if 0 <= respMan <= 1 and lower_msg in ['s', 'sim']:
                if respMan == 0:
                    formulario = "https://docs.google.com/forms/d/e/1FAIpQLSehB1eDeL1hAObF-vS2woB3pWhl4UBqq098FEwfmQiKK8r2Rg/viewform"
                else:
                    formulario = "https://docs.google.com/forms/d/e/1FAIpQLSdQ66y9yJTcFTTmyLp3SskI2aYLLRLasu2Wym1HyWyQ6LV8OQ/viewform"
                message = f'''Antes de iniciar sua participação você precisa se submeter a uma curadoria e para isso é necessário preencher o formulário abaixo:

Formulário: {formulario}'''
                resps_order = 0
                respMan = -1
            
            elif  0 <= respMan <= 1 and lower_msg in ['n', 'nao', 'não']:
                message = "Obrigada pelo contato. Até a próxima"
                
                resps_order = 0
                respMan = -1

            elif 'voltar' in lower_msg:
                resps_order = 0
                respMan = -1

            elif respMan == 2 or (resps_order == 3 and respMan == 0 and lower_msg == 's'):
                if '1' in lower_msg:
                    message = '''É necessário participar da nossa curadoria onde você preenche o formulário, caso seu produto seja aprovado e tenha vaga para seu segmento entraremos em contato com você.
Formularios:

    - Feira do Lindu: https://docs.google.com/forms/d/e/1FAIpQLSehB1eDeL1hAObF-vS2woB3pWhl4UBqq098FEwfmQiKK8r2Rg/viewform?fbclid=PARlRTSANH6AZleHRuA2FlbQIxMQABp_bCJf2BvouJmcWu2viWXpQOd82FalW79pkVeY86JDMseEfOxT9cmy0I8tD6_aem_EDCpzp88msiH6XWQnODg1w
    
    - Festival de Sabores Apipucos: https://docs.google.com/forms/d/e/1FAIpQLSdQ66y9yJTcFTTmyLp3SskI2aYLLRLasu2Wym1HyWyQ6LV8OQ/viewform?fbclid=PARlRTSANH6B1leHRuA2FlbQIxMQABp-Svb6mRZ-r0KmC9554r1n1Rf-_ThI1yQ9GPOJsfvPjZonW1b0NW-o8RVTJj_aem_fB44HkVYPilUH-vsuBs7Jw 

Deseja continuar no menu de dúvidas? digite 'S' para continuar ou 'N' para voltar para o menu principal'''

                    resps_order = 3
                    respMan = 0
                    
                
                elif '2' in lower_msg:
                    message = '''Taxa de participação:
                    
    Feira do Lindu: 10% do faturamento total no dia da Feira ou R$150,00 caso seu faturamento seja inferior a R$1500,00;
    Festival de Sabores Apipucos: 10% do faturamento total no dia da Feira ou R$180,00 caso seu faturamento seja inferior a R$1800,00;

    Obs: As taxas são semanais, não temos taxas mensais e você só paga as edições que participar.
    
Deseja continuar no menu de dúvidas? digite 'S' para continuar ou 'N' para voltar para o menu principal'''

                    resps_order = 3
                    respMan = 0
                
                elif '3' in lower_msg:
                    message = '''A Feira do Lindu acontece todos os domingos, das 15:00 as 21:00.

O Festival de Sabores de Apipucos acontece aos sábados das 12:00h as 21:00h.
                    
Deseja continuar no menu de dúvidas? digite 'S' para continuar ou 'N' para voltar para o menu principal'''
                    resps_order = 3
                    respMan = 0
                                        
                elif '4' in lower_msg:
                    message = '''Está incluso:
                        
    1 - Montagem da barraca (medida: 1.40m de comprimento x .70m de largura) no horário da Feira; 
    2 - Todo o suporte com relação a dúvidas na maquineta (durante as Feiras do Lindu e Apipucos é obrigatório o uso da maquineta disponibilizada pelo parque);
    3 - Supervisão de bombeiros;
    4 - Suporte na hora da Feira, com a supervisora da mesma; 
    5 - É disponibilizado um ponto de luz e tomada para apenas carregamento de celular ou maquineta (não aceitamos nenhum equipamento elétrico);
                    
Deseja continuar no menu de dúvidas? digite 'S' para continuar ou 'N' para voltar para o menu principal'''

                    resps_order = 3
                    respMan = 0
                    
                elif '5' in lower_msg:
                    message = '''Não pode. O expositor será adicionado ao grupo do Whatsapp onde será disponibilizado semanalmente o mapa com seu número e localização. Porém se o expositor se sentir insatisfeito com sua localização, deverá proucurar a organização para tentar realocar seu lugar. 
                    
É importante lembrar que não fica garantida a mudança do local do expositor, porque prezamos sempre pelo bem coletivo da Feira.

Não temos localização e números fixos, mas prezamos por sempre tentar ao máximo deixar o expositor no seu lugar e numeração para facilitar ao máximo para o cliente. 

Deseja continuar no menu de dúvidas? digite 'S' para continuar ou 'N' para voltar para o menu principal'''

                    resps_order = 3
                    respMan = 0
                    
                elif '6' in lower_msg:
                    message = '''Permitimos estantes, mesas e araras em material de pallet, com medida máxima de 80cm (que será o espaço disponibilizado em apenas uma lateral da barraca do expositor, deixando um lado sempre livre para circulação).

Obs: É necessário enviar foto do material extra para aprovação.

Deseja continuar no menu de dúvidas? digite 'S' para continuar ou 'N' para voltar para o menu principal'''
                    resps_order = 3
                    respMan = 0

                elif '7' in lower_msg:
                    message = '''Não temos vaga para os seguintes segmentos: 

1 - Prata;
2 - Bijus finas;
3 - Gastronomia;
4 - Papelaria;
5 - Aromas e Velas;
6 - Vestuário infantil

Deseja continuar no menu de dúvidas? digite 'S' para continuar ou 'N' para voltar para o menu principal''

                    resps_order = 3
                    respMan = 0
                    
                elif '0' in lower_msg:
                    message = '''Ok, qual é a sua dúvida?'''
                    resps_order = 3
                    respMan = 1
            
                else:
                    message = '''Não entendi!
Digite o número da dúvida desejada, ou digite 'Voltar' para voltar para o menu principal:'''
            else:    
                message = '''Não entendi!

Você tem interesse em participar? responda com 'S' para sim ou 'N' para não. '''
    
    elif resps_order == 3:

        if respMan != 1:
            message ='''Não entendi!
            
Deseja continuar no menu de dúvidas? digite 'S' para continuar ou 'N' para voltar para o menu principal'''

    print(f"\n\nRespman dentro do respClient: {respMan}")
    print(f"\n\nResp order dentro do respClient: {resps_order}\n\n")
    return message, respMan, resps_order"""