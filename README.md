# Libris

Libris é uma aplicação para traduzir livros digitais e acompanhar o andamento do trabalho em uma fila. Envie um livro, escolha os idiomas e selecione entre a tradução pela API Gemini ou a tradução local do Argos Translate.

O projeto tem uma interface web e uma API Python. Elas ficam no mesmo repositório, mas são publicadas separadamente: a interface no GitHub Pages e a API no Render.

## O que o Libris faz

- Recebe arquivos PDF, EPUB e MOBI.
- Traduz o conteúdo usando Gemini ou Argos Translate.
- Permite escolher o idioma de origem, o idioma de destino e o formato de saída.
- Acompanha, cancela, retoma e remove traduções na fila.
- Guarda checkpoints para retomar traduções interrompidas.
- Exporta traduções em PDF ou EPUB.
- Permite instalar pacotes de idiomas Argos pela interface.
- Protege as operações de tradução com login GitHub quando executado em produção.

PDFs digitalizados precisam passar por OCR antes do envio. A conversão de MOBI requer Calibre instalado no computador ou servidor que executa a API. A formatação de livros traduzidos é aproximada e pode não preservar integralmente imagens, paginação, navegação ou o design original.

## Como funciona

```text
Navegador
  └── Interface React / TypeScript / Vite
        └── API FastAPI
              ├── Gemini Cloud API
              └── Argos Translate local
```

- **Gemini:** usa a internet e uma chave de API configurada somente no backend. Podem se aplicar limites, cotas e cobranças do provedor.
- **Argos Translate:** traduz no ambiente onde a API está executando, usando pacotes de idiomas instalados. Não é um motor que roda no navegador do visitante.
- **Arquivos e histórico:** ficam em `backend/data/jobs`. O projeto não usa banco de dados. Em hospedagem com disco efêmero, arquivos, histórico, checkpoints e pacotes Argos podem ser perdidos.
- **Autenticação:** em produção, qualquer pessoa com uma conta GitHub pode entrar e acessar livros e traduções; não há allowlist.

## Tecnologias

- Interface: React, TypeScript, Vite e Tailwind CSS.
- API: Python 3.11, FastAPI e Uvicorn.
- Tradução na nuvem: Gemini.
- Tradução local: Argos Translate.
- Hospedagem: GitHub Pages para a interface e Render para a API.

## Executar localmente

Requisitos: Python 3.11 e Node.js 20 ou superior.

### Iniciar a API

No PowerShell, a partir da raiz do repositório:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edite `backend/.env` e defina `GEMINI_API_KEY` se for usar Gemini. A chave deve permanecer no backend e não pode ser enviada ao GitHub.

Para instalar sequencialmente os pacotes Argos prioritários:

```powershell
python install_argos_language.py
```

O instalador consulta o índice oficial, ignora pares já instalados e tenta cada pacote individualmente. O conjunto usa `en ↔ pt`, `pt ↔ es`, e pares em ambas as direções entre inglês e alemão, francês e italiano. Assim, o Argos compõe traduções entre todos os seis idiomas sem baixar todos os pares do catálogo. O índice oferece `pt` (Portuguese), não um pacote separado `pt-BR`.

Inicie a API:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

A API estará em `http://127.0.0.1:8000`; sua documentação interativa fica em `http://127.0.0.1:8000/docs`.

### Iniciar a interface

Em outro terminal, na raiz do repositório:

```powershell
cd frontend
npm ci
npm run dev
```

Abra `http://127.0.0.1:5173`. Para usar outro endereço de API, copie `frontend/.env.example` para `frontend/.env.local` e ajuste `VITE_API_URL` para a origem do backend, sem `/api` ao final.

## Publicação

O repositório é `https://github.com/luilencina/libris`. Frontend e backend permanecem juntos no código, mas cada um tem seu próprio serviço de hospedagem.

### API no Render

1. Crie ou sincronize o Blueprint do Render com este repositório e o arquivo `render.yaml`. O serviço está configurado com o nome `libris-api`.
2. Depois de renomear o serviço no Render, confirme o domínio atribuído. A configuração assume `https://libris-api.onrender.com`; se o Render mostrar outro domínio, atualize `GITHUB_CALLBACK_URL` para `https://<domínio-real>/api/auth/github/callback` e use esse mesmo domínio nos próximos passos.
3. Crie uma GitHub OAuth App em **Settings → Developer settings → OAuth Apps**. Configure a Homepage URL como `https://luilencina.github.io/libris/` e o Authorization callback URL com o callback do Render confirmado no passo anterior.
4. No build, o Render instala os dez pares direcionais definidos em `backend/install_argos_language.py`, um por vez, em `backend/argos-packages`. Falhas individuais aparecem nos logs do build e não impedem a API de iniciar; pares ausentes ficam indisponíveis até serem instalados. A instalação não ocorre durante a inicialização da API.
5. Configure `GEMINI_API_KEY`, `GITHUB_CLIENT_ID` e `GITHUB_CLIENT_SECRET` nas variáveis de ambiente do Render. `APP_SESSION_SECRET` é gerado pelo Blueprint. Não coloque nenhum desses segredos no frontend nem em arquivos versionados.
6. Qualquer conta GitHub pode entrar. O endpoint público de saúde é `/api/health`; a documentação da API é `/docs`.

O CORS permite a origem `https://luilencina.github.io`. CORS não substitui autenticação: as rotas de livros e traduções continuam protegidas pelo login.

#### Memória e diagnóstico do Argos

- O processo usa CPU, INT8 e uma thread CTranslate2. Uma tradução composta é executada em etapas: cada modelo é liberado antes de carregar o próximo. A extração de livros, os jobs de tradução e a instalação de pacotes são serializados para evitar picos simultâneos; modelos não são carregados todos no startup.
- A extração de PDF/EPUB e a criação dos arquivos de chunks são feitas incrementalmente. Textos e estilos traduzidos são lidos do disco durante a exportação, em vez de acumular o livro inteiro na RAM.
- O catálogo oficial consultado contém os dez pares escolhidos. Uma medição local real de `en → pt` com INT8 e uma thread atingiu **465,2 MiB de RSS** neste Windows; após liberar o tradutor, o RSS observado foi **382,4 MiB**. Isso não equivale a uma medição no Render e deixa pouca margem em uma instância de 512 MB. Não é possível garantir que todos os modelos e livros caibam no plano Free sem medir a instância real; se o diagnóstico ou os logs se aproximarem de 512 MB, use pelo menos o plano Render de 2 GB ou reduza a carga.
- O conjunto mínimo inclui dez arquivos de modelo; o tamanho comprimido estimado a partir do catálogo é aproximadamente **0,82 GiB**. O tamanho instalado e o espaço livre exatos são impressos nos logs do build. Confirme que o deploy completa e que há espaço suficiente no filesystem do serviço.
- Depois do login, use `GET /api/languages/diagnostics` para consultar pares instalados e utilizáveis. Para executar uma tradução curta real e conferir RSS atual/pico no Render, use `GET /api/languages/diagnostics?test=true` com o token da sessão:

```powershell
curl.exe -H "Authorization: Bearer <TOKEN_DA_SESSAO>" "https://libris-api.onrender.com/api/languages/diagnostics?test=true"
```

O resultado contém `installed_direct_pairs`, `usable_pairs`, `test_translation` e `process_memory`. A rota exige login. Os logs do build mostram cada instalação, falhas por par, uso do diretório dos modelos e espaço restante.

### Interface no GitHub Pages

1. Em **Settings → Pages**, selecione **GitHub Actions** como fonte de publicação.
2. O workflow publica automaticamente a cada envio para `main` ou pode ser executado manualmente pela aba **Actions**. Por padrão, ele usa `https://libris-api.onrender.com` como API.
3. Se o Render atribuir outro domínio ao serviço, configure a variável de Actions `VITE_API_URL` com a origem HTTPS real do backend, sem `/api` ao final. Essa URL não é um segredo.

O workflow instala as dependências, compila `frontend` e publica `frontend/dist`. O endereço esperado é `https://luilencina.github.io/libris/`.

## Limitações de hospedagem

- O plano gratuito do Render é indicado para testes e projetos pessoais, não para produção. Ele pode suspender após inatividade e demorar para responder na primeira solicitação.
- O sistema de arquivos gratuito é efêmero. Livros enviados, traduções, checkpoints, histórico e pacotes Argos podem desaparecer ao suspender, reiniciar ou publicar uma nova versão.
- Para persistência, configure um disco persistente compatível no backend e defina `DATA_DIR` para o ponto de montagem.
- O plano Free oferece 512 MB de RAM. A medição local de `en → pt` já chegou a 465,2 MiB; a memória no Render depende da imagem/runtime e dos modelos usados. Não considere o plano de 512 MB validado até executar o diagnóstico e testar a tradução de maior consumo na instância publicada. O filesystem é efêmero: os modelos instalados no build fazem parte da versão implantada, mas instalações feitas durante a execução podem desaparecer ao reiniciar ou suspender.
- MOBI também requer Calibre, que não está incluído na configuração padrão.
- Qualquer conta GitHub pode usar o serviço. O login confirma a identidade, mas não limita quem pode consumir a cota Gemini, a memória e o armazenamento. Para um serviço público, configure rate limiting, cotas por conta e monitoramento de custos.

## Privacidade e uso responsável

A chave Gemini permanece no backend. Os livros enviados são processados pela API hospedada; ao selecionar Gemini, o conteúdo necessário à tradução é enviado ao provedor. Use apenas livros que você tem direito de processar. O Libris não remove DRM nem contorna restrições de documentos.
