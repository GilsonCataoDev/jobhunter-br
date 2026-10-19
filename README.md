# jobhunter-br

Robô de busca e candidatura de vagas para o mercado brasileiro. Ele **coleta** vagas (Gupy, InfoJobs, vaga-ja.com), **filtra** o que não serve para o seu perfil, **pede a sua aprovação** pelo Telegram e, só então, **se candidata** na Gupy preenchendo as perguntas com respostas que você mesmo cadastrou.

Feito para quem procura vaga de **entrada/júnior/estágio** e quer parar de abrir dezenas de abas. Tudo roda no seu computador. Não há servidor, não há conta de terceiros e nenhuma senha fica guardada em código.

> ⚠️ **Leia antes de usar**
> - Candidatura automática pode ir contra os termos de uso de alguns sites. Você usa por sua conta e risco.
> - O robô **nunca** preenche documentos (RG, CPF, CNH…), dados de família ou dados sensíveis: ele para e te pergunta.
> - O robô **não faz testes/avaliações** por você e **não resolve CAPTCHA**.
> - Respostas enviadas na Gupy **não podem ser editadas depois**. Por isso existe o modo de teste (*dry-run*), que preenche mas não salva. Use-o sempre antes do envio real.

---

## Sumário
1. [Como funciona](#como-funciona)
2. [Instalação](#instalação)
3. [Configuração](#configuração)
4. [Uso passo a passo](#uso-passo-a-passo)
5. [Fontes de vagas](#fontes-de-vagas)
6. [Como o robô decide: filtros](#como-o-robô-decide-filtros)
7. [Como o robô responde as perguntas](#como-o-robô-responde-as-perguntas)
8. [Trabalhos presenciais ou vagas específicas](#vagas-presenciais-ou-específicas)
9. [Segurança e limites](#segurança-e-limites)
10. [Testes](#testes)
11. [Estrutura do projeto](#estrutura-do-projeto)
12. [Problemas comuns](#problemas-comuns)
13. [Limitações conhecidas](#limitações-conhecidas)

---

## Como funciona

```
 Fase 1: coleta                Fase 2: aprovação               Fase 3: envio
 ─────────────────             ─────────────────────           ─────────────────────
 Gupy / InfoJobs /      ┌───►  Bot do Telegram        ┌───►    Navegador (Playwright)
 vaga-ja.com            │      /fila  → você aprova   │        abre a vaga na Gupy,
        │               │      /pendencias → você     │        preenche e envia
        ▼               │      responde o que falta   │        (ou só testa, no dry-run)
   filtros (rules.py)   │               │             │               │
        │               │               ▼             │               ▼
        ▼               │      banco SQLite local ────┘        registro das candidaturas
 banco SQLite ──────────┘      (vagas, pendências,
 (status: shortlisted)          respostas aprendidas)
```

Cada vaga passa por estados: `shortlisted` (passou nos filtros) → `approved` (você aprovou) → `sending` → `sent`. Vagas com pergunta sem resposta segura ficam esperando em *pendências* e **não são enviadas**.

## Instalação

Requisitos: **Python 3.11+** e, para a Fase 3, um navegador Chromium instalado pelo Playwright.

```bash
git clone https://github.com/GilsonCataoDev/jobhunter-br.git
cd jobhunter-br
python -m venv .venv
# Windows:  .venv\Scripts\activate        Linux/Mac:  source .venv/bin/activate
pip install -r requirements.txt

# Só para a Fase 3 (envio): navegador controlado pelo robô
pip install playwright
playwright install chromium
```

## Configuração

### 1. Seu perfil e respostas: `jobhunter/answers.yml`

Copie o modelo e **edite com os seus dados**. Esse arquivo fica **fora do git** (está no `.gitignore`).

```bash
cp jobhunter/answers.example.yml jobhunter/answers.yml
```

O que ajustar no bloco `perfil:`: pretensão salarial por tipo de vaga (só estas 3 chaves são reconhecidas: `estagio` para estágios, `farmaceutico` para vagas com "farmac" no título e `junior` para todo o resto), último salário, estado, cidade e LinkedIn. Em `regras:` ficam as respostas automáticas a perguntas comuns (ver [abaixo](#como-o-robô-responde-as-perguntas)). **Só coloque ali o que você realmente quer responder sozinho.** Sem `answers.yml`, o robô usa o modelo com valores fictícios.

### 2. O que buscar: `jobhunter/config.yml`

| Bloco | Para que serve |
|---|---|
| `gupy.termos` | Palavras buscadas na Gupy (só vagas remotas) |
| `faixas` | Prioridade por palavra do título: 1 = melhor. Vaga cujo título não casa com nenhuma faixa é descartada |
| `titulo_proibido` | Títulos descartados (sênior, pleno, gerente, PCD…) |
| `salario_minimo_efetivo` | Descarta vagas efetivas que informem salário abaixo disso |
| `infojobs` / `vagaja` | Liga/desliga as fontes extras (`ativo: true/false`) |
| `executor` | Limite diário de envios, pausa entre vagas, parada após falhas seguidas |

Os valores que vêm no repositório servem a quem busca **TI júnior/estágio e administrativo remoto**. Para outra área, troque `termos`, `faixas` e `titulo_proibido`.

### 3. Telegram (opcional, mas é o jeito confortável de aprovar)

1. No Telegram, fale com **@BotFather**, use `/newbot` e guarde o **token**.
2. Mande qualquer mensagem para o seu bot e descubra o seu **chat id** (por exemplo com o bot `@userinfobot`).
3. Defina as variáveis de ambiente (nunca coloque em código):

```bash
# Linux/Mac
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="123456789"
# Windows (PowerShell)
$env:TELEGRAM_BOT_TOKEN = "123456:ABC..."; $env:TELEGRAM_CHAT_ID = "123456789"
```

Só o chat configurado é atendido; mensagens de outras pessoas são ignoradas. Sem Telegram, o resumo é impresso no terminal.

## Uso passo a passo

### Passo 1 — Coletar e filtrar vagas (Fase 1)
```bash
python -m jobhunter.run              # coleta, filtra, grava no banco e manda o resumo
python -m jobhunter.run --dry-run    # banco em memória: só mostra o que passaria
python -m jobhunter.run --no-notify  # grava no banco, mas imprime em vez de enviar ao Telegram
```
Nada é enviado a empresas nesta fase.

### Passo 2 — Aprovar e responder pendências (Fase 2)
```bash
python -m jobhunter.bot
```
No Telegram:

| Comando | O que faz |
|---|---|
| `/fila` | Mostra as vagas novas, com botões **Aprovar / Pular** |
| `/pendencias` | Lista perguntas que o robô não soube responder |
| `/r <id> <resposta>` | Responde uma pendência (a resposta é guardada e reaproveitada em perguntas iguais) |
| `/feito <id>` | Marca como resolvida uma pendência sensível que **você** preencheu direto no site |
| `/aprovadas` | Vagas aprovadas e prontas para envio |
| `/ajuda` | Lista os comandos |

### Passo 3 — Login na Gupy (uma vez só)
```bash
python -m jobhunter.executor.driver_playwright --login
```
Abre uma janela real do Chromium. **Você** entra na sua conta Gupy (o robô não digita senha). Quando aparecer "Minhas candidaturas", espere uns 10 segundos e feche a janela. A sessão fica gravada em `~/.jobhunter/browser-profile` (mude com a variável `JOBHUNTER_PROFILE`).

### Passo 4 — Teste sem enviar (dry-run) ✅ sempre faça
```bash
python -m jobhunter.executor.run_apply --limit 1
```
Preenche a candidatura, tira um print em `jobhunter/data/shots/` e **não salva nada**. Resultados possíveis:

| Resultado | Significado |
|---|---|
| `dry_run_ready` | Tudo certo: está pronto para o envio real |
| `pending` | Faltam respostas seguras: responda no bot (`/pendencias`) |
| `already_applied` | Você já tinha se candidatado |
| `needs_human` | Tela desconhecida, CAPTCHA, pedido de documento ou sessão expirada |
| `error` | Falha técnica: veja o print e o motivo |

### Passo 5 — Envio real
```bash
python -m jobhunter.executor.run_apply --send --limit 3
```
Opções: `--limit N`, `--headless` (sem janela), `--db caminho`. Ao enviar, o robô marca a vaga como `sending` **antes** de mexer no site, para nunca candidatar duas vezes, e registra no arquivo `auto_apply/applied_log.csv`.

### Extra — ver onde você já se candidatou
```bash
python -m jobhunter.executor.history
```
Lê "Minhas candidaturas" da Gupy e mostra o que **não** está no seu registro local (a Gupy nem sempre lista as mais antigas).

## Fontes de vagas

| Fonte | Como lê | Envio automático? |
|---|---|---|
| **Gupy** | Página pública de busca, só vagas remotas | **Sim** (Fase 3) |
| **InfoJobs** | Busca com filtro "home office"; abre cada vaga e lê o JobPosting (JSON-LD) | Não: você recebe o link |
| **vaga-ja.com** | Sitemap de vagas + JobPosting (JSON-LD) | Não: você recebe o link |

Sites externos têm formulário e login próprios, por isso o robô só **lista** as vagas deles. Os coletores respeitam o `robots.txt` dos sites e fazem pausa entre as requisições. Para adicionar uma fonte nova, crie `jobhunter/collectors/<nome>.py` com uma função `collect(...)` que devolva `(vagas, erros)` no mesmo formato (veja `jsonld.normalize`) e ligue-a em `run.coletar_tudo`.

## Como o robô decide: filtros

Em `jobhunter/rules.py`, uma vaga é **descartada** se:

- for PJ, banco de talentos ou aprendiz; o título tiver palavra proibida (sênior, pleno, gerente…); estiver fora das suas `faixas`;
- o prazo já passou ou foi publicada há mais de 30 dias; parecer golpe;
- exigir **inglês avançado/fluente** ou **espanhol**;
- for "remota" mas exigir presença (presencial disfarçado);
- exigir **superior completo**, formação fora do seu perfil, **experiência** anterior ou mais de 1 ano de experiência (itens "desejável/diferencial" não contam; "sem experiência" também não);
- informar salário abaixo do mínimo configurado.

Vagas que passam podem trazer **avisos** (horário fixo, cita presencial, temporário). Ajuste as listas e expressões no topo de `rules.py`. A empresa também é deduplicada: se você já se candidatou a ela (consulta o registro e o histórico), a vaga nova é descartada.

## Como o robô responde as perguntas

Para cada pergunta do formulário, na ordem:

1. **Sensível** → *nunca responde.* Documentos, filiação, nascimento, endereço, raça/gênero/PCD, dados bancários. Vira pendência marcada como sensível para **você** preencher.
2. **Pergunta sobre horário específico** → pendência.
3. **Sim/Não com salário embutido** → só responde "Sim" se o valor cobre a sua pretensão.
4. **Regras do `answers.yml`** (a primeira que casar vence), por exemplo "alguém indicou você?" → Não, "maior de 18 anos?" → Sim, pretensão salarial → número ou a faixa que contém o seu valor.
5. **Respostas que você já deu** (aprendidas pelo `/r`) para a mesma pergunta.
6. Nada casou → **pendência**; a candidatura não é enviada.

Para criar uma regra, adicione uma linha em `regras:` com `match` (expressão regular, **sem acento e em minúsculas**) e `responder` ou `responder_perfil`. Use `{empresa}` no `match` para o nome da empresa. Rode os testes depois.

## Vagas presenciais ou específicas

Por padrão, o coletor busca **somente remoto**. Para vagas presenciais de uma região (por exemplo, uma profissão regulamentada), use o script de lote por estado:

```bash
# 1) teste: lista as vagas achadas e preenche sem salvar
python -m jobhunter.lote_por_estado --estados Pernambuco Alagoas --termos "farmacêutico" --titulo farmac
# 2) envio real, depois de conferir a lista e as respostas
python -m jobhunter.lote_por_estado --estados Pernambuco Alagoas --termos "farmacêutico" --titulo farmac --send --limite 20
```

Ele só considera vagas **efetivas da Gupy** cujo título contém o trecho de `--titulo`. **Atenção:** as vagas desse lote entram como aprovadas direto, **sem passar pelo `/fila`**; a aprovação é o seu `--send`. Para vagas com "farmac" no título, a pretensão vem de `perfil.pretensao.farmaceutico`; para as demais, de `junior`. Se a chave faltar, o robô para e pergunta.

## Segurança e limites

- **Nunca** preenche documentos ou dados sensíveis, **nunca** faz testes por você, **nunca** resolve CAPTCHA, **nunca** retira candidaturas.
- Sem `--send`, nada é salvo (dry-run é o padrão).
- **Limite diário** de envios (`executor.limite_diario`), pausa aleatória entre vagas e parada após falhas seguidas.
- **Trava anti-duplicidade**: se o processo cair no meio de um envio, a vaga fica em `sending` e o robô se recusa a rodar de novo até você conferir na Gupy e corrigir o status no banco.
- **Dados pessoais ficam fora do git:** `answers.yml`, `jobhunter/data/` (banco, prints) e `auto_apply/applied_log.csv` estão no `.gitignore`. O token do Telegram vive só em variável de ambiente. Antes de publicar um fork, confira com `git status` que nada disso foi adicionado.
- Visitar a página de candidatura de uma vaga cria um **rascunho** na sua conta Gupy. Se o robô parar no meio, pode sobrar um rascunho: remova no site se não quiser mantê-lo.

## Testes

```bash
python -m unittest discover -s jobhunter/tests -t .
```
Os testes não acessam a internet nem o seu `answers.yml`: usam o modelo e um navegador falso que simula as telas da Gupy.

## Estrutura do projeto

```
jobhunter/
├── run.py                 # Fase 1: coleta → filtro → banco → resumo
├── collectors/            # gupy.py, infojobs.py, vagaja.py, jsonld.py
├── rules.py               # filtros de vaga
├── answers.py             # motor de respostas  (+ answers.example.yml, o modelo)
├── approval.py            # pendências e aprovação
├── bot.py / notify.py     # Telegram
├── db.py                  # SQLite local (jobhunter/data/jobs.db)
├── config.yml             # o que buscar e limites
├── executor/
│   ├── flow.py            # fluxo da candidatura na Gupy (independe do navegador)
│   ├── driver_playwright.py  # navegador real + login
│   ├── run_apply.py       # lote: limite diário, trava, registro
│   ├── history.py         # lê "Minhas candidaturas"
│   └── gupy_dom.js        # lê/marca campos do formulário
└── tests/
```

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `LOGIN: sessão da Gupy expirada` | Rode o [Passo 3](#passo-3--login-na-gupy-uma-vez-só) de novo |
| `needs_human: tela desconhecida` | Abra o print em `jobhunter/data/shots/`: a página pode ter mudado, ou ainda estava carregando |
| `CAPTCHA` | Resolva você mesmo no site e rode de novo |
| O robô se recusa a rodar (`em 'sending'`) | Uma execução anterior caiu no meio. Confira na Gupy se a candidatura saiu e corrija o status da vaga no banco |
| Vaga que parecia boa foi descartada | Veja o motivo no banco (`jobs.reason`) e ajuste `config.yml` / `rules.py` |
| No Windows, `\n` virou caractere estranho em `answers.yml` | Edite o arquivo num editor de texto e use as expressões já existentes como exemplo |

## Limitações conhecidas

- Só envia sozinho na **Gupy**. Perguntas com formato muito diferente (upload de arquivo, teste, vídeo) param para você.
- O histórico da Gupy mostra no máximo as candidaturas mais recentes; por isso o registro local é a fonte principal contra duplicidade.
- Sites mudam: se a Gupy alterar o HTML, os coletores e `gupy_dom.js` precisam de ajuste. Os testes ajudam a achar o que quebrou.

## Contribuindo

Issues e pull requests são bem-vindos. Antes de abrir um PR, rode os testes e **não inclua dados pessoais** (nomes, e-mails, telefones, prints de candidaturas reais).

## Licença

[MIT](LICENSE)
