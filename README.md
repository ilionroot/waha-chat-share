# waha-chat-share

Compartilha **uma** conversa do WhatsApp com outra pessoa numa página web, usando uma instância local do [WAHA](https://waha.devlike.pro/).

A pessoa vê a conversa (texto, foto, vídeo, áudio, documentos), responde marcando mensagens e manda texto e imagem. O WAHA fica só em `127.0.0.1`; o `server.py` expõe apenas o chat definido em `CHAT_ID`, atrás de usuário e senha.

## Subir

1. `cp .env.example .env` e preencha as senhas (ex.: `openssl rand -hex 24`).
2. `docker compose up -d`
3. Crie a sessão com store (motor NOWEB):
   ```sh
   curl -X POST http://127.0.0.1:3000/api/sessions -H "X-Api-Key: $WAHA_API_KEY" -H 'Content-Type: application/json' \
     -d '{"name":"default","start":true,"config":{"noweb":{"store":{"enabled":true,"fullSync":true}}}}'
   ```
4. Escaneie o QR em http://localhost:3000/dashboard (configure a API key no worker).
5. `./list-chats.sh` e copie o id da conversa para `CHAT_ID` no `.env`.
6. `python3 server.py` e acesse `http://<seu-ip>:8088` (no Fedora: `sudo firewall-cmd --add-port=8088/tcp`).

## Vigia da sessão

`watchdog.sh` reinicia a sessão se ela cair. Para rodar a cada minuto via systemd do usuário:

```sh
cp systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now waha-watchdog.timer
```

## Limitações

- Sem tempo real: a página busca as mensagens ao abrir, ao clicar em "Atualizar" e depois de enviar.
- Mensagens recebidas com a sessão fora do ar não são recuperadas; nesse caso, desconecte e escaneie o QR de novo para refazer a sincronização.
- HTTP sem TLS: use só em rede confiável.
