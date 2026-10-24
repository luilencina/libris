# Libris

Aplicação web para traduzir livros em PDF e EPUB usando a API Gemini ou o Argos Translate offline. A interface React/Vite e a API FastAPI podem ser executadas localmente ou hospedadas separadamente.

## Tecnologias e requisitos

- Frontend: React, TypeScript, Vite e Tailwind CSS.
- Backend: Python 3.11, FastAPI e Uvicorn.
- Node.js 20 ou superior para desenvolvimento e build.
- Gemini: chave de API configurada somente no backend.
- Argos: pacotes de idioma instalados no ambiente em que o backend estiver rodando.

O backend armazena arquivos, checkpoints e histórico em `backend/data/jobs`; não há banco de dados. Na hospedagem, Argos executa no servidor do backend — não no navegador nem no computador de quem visita o GitHub Pages.

## Executar localmente

No PowerShell, a partir da raiz do projeto:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edite `backend/.env` para preencher `GEMINI_API_KEY` se for usar o Gemini. Essa chave não deve ser colocada no frontend nem enviada ao GitHub.

Instale um pacote Argos de inglês para português (opcional):

```powershell
python install_argos_language.py
```

Inicie o backend:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

A API e a documentação ficam em `http://127.0.0.1:8000` e `http://127.0.0.1:8000/docs`.

Em outro terminal:

```powershell
cd frontend
npm ci
npm run dev
```

A interface abre em `http://127.0.0.1:5173`. Para apontar o frontend local a outro backend, copie `frontend/.env.example` para `frontend/.env.local` e ajuste `VITE_API_URL` para a origem da API, sem `/api` no final.

## Publicação

Recomendação: mantenha o frontend e o backend no mesmo repositório, chamado `libris`. Isso facilita atualizar e versionar as duas partes juntas; o deploy continua separado: GitHub Pages publica o frontend e o Render executa a API a partir da pasta `backend`.

### Backend no Render

1. Crie um Blueprint no Render usando este repositório e o arquivo `render.yaml`.
2. Crie uma GitHub OAuth App em **Settings → Developer settings → OAuth Apps**. Use `https://luilencina.github.io/libris/` como **Homepage URL** e `https://novel-translator-api.onrender.com/api/auth/github/callback` como **Authorization callback URL**. Se o Render gerar outro domínio para o serviço, use o domínio real na URL de callback e na variável `GITHUB_CALLBACK_URL`.
3. Informe `GEMINI_API_KEY`, `GITHUB_CLIENT_ID` e `GITHUB_CLIENT_SECRET` nas variáveis de ambiente do backend no Render. O Blueprint gera `APP_SESSION_SECRET`; mantenha-o privado. Nunca coloque esses valores no frontend ou em arquivos versionados.
4. O Blueprint restringe o login ao usuário GitHub `luilencina` por padrão. Altere `GITHUB_ALLOWED_USERS` no Render para permitir outras contas. O login vale por oito horas e o token fica na sessão da aba do navegador.
5. A verificação pública de saúde fica em `/api/health`; a documentação da API, em `/docs`.

A autenticação GitHub protege as rotas de livros e traduções. O CORS permite somente a origem `https://luilencina.github.io`; CORS não substitui autenticação.

### Frontend no GitHub Pages

1. Nas configurações do repositório GitHub, crie a variável de Actions `VITE_API_URL` com a origem HTTPS do backend Render, sem `/api` no final. Essa URL é pública e não é uma credencial.
2. Em **Settings → Pages**, escolha **GitHub Actions** como fonte de publicação.
3. Envie as alterações para a branch `main` ou execute manualmente o workflow **Deploy frontend to GitHub Pages**.

O workflow instala as dependências com `npm ci`, valida a URL HTTPS, gera o bundle com o caminho `/libris/` e publica `frontend/dist`. A URL esperada é `https://luilencina.github.io/libris/`.

### Limitações do plano gratuito

- O Render informa que instâncias gratuitas não são indicadas para produção. O Blueprint usa o plano gratuito apenas para testar a integração; antes de uso real, escolha uma instância paga ou outro serviço adequado.
- O serviço gratuito do Render pode suspender quando fica sem uso e demorar para responder no primeiro acesso.
- O serviço suspende após 15 minutos sem tráfego; o sistema de arquivos gratuito é efêmero. Livros enviados, traduções parciais, histórico e pacotes Argos podem desaparecer ao suspender, reiniciar ou fazer deploy. O histórico também não é compartilhado entre réplicas.
- Para persistência, configure um disco persistente no backend e `DATA_DIR` apontando para o ponto de montagem. Esse recurso exige um plano compatível com disco persistente.
- A memória do plano gratuito pode não ser suficiente para determinados pacotes Argos. MOBI também depende do Calibre, que não vem instalado na configuração padrão do Render.
- O site do Pages é público, mas as rotas de livros e traduções exigem login GitHub e uma conta listada em `GITHUB_ALLOWED_USERS`. CORS não impede chamadas feitas por clientes fora do navegador; a autenticação é que restringe o acesso. Não há limite de uso por usuário, então adicione rate limiting se autorizar outras contas além da sua.

## Formatos e limitações

- PDF e EPUB de texto podem ser enviados; PDF digitalizado requer OCR.
- MOBI depende do Calibre no computador/servidor do backend.
- EPUB e PDF traduzidos preservam texto e algumas características de parágrafo, mas não reproduzem integralmente imagens, navegação, paginação ou design do livro original.
- A tradução Gemini depende de conectividade, limites e preços definidos pelo provedor.
- Argos funciona offline depois de baixar os pacotes de idioma; a qualidade varia conforme o par de idiomas.
- Use apenas livros que você tem direito de processar. O aplicativo não remove DRM nem contorna restrições de documentos.
