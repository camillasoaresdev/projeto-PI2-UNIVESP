# Urban Barber

## Executar o sistema

1. Instale o Python 3 no Windows, marcando a opção `Add Python to PATH`.
2. Abra o PowerShell nesta pasta do projeto.
3. Execute:

```powershell
python server.py
```

4. Acesse `http://127.0.0.1:8000` no navegador.

O arquivo `database/urban_barber.db` é criado automaticamente na primeira execução.

## Validação de usuários

- O cadastro exige nome, e-mail, telefone, perfil e senha com pelo menos 8 caracteres.
- O e-mail e o telefone são únicos; o login pode usar qualquer um dos dois.
- As senhas são armazenadas com PBKDF2-HMAC-SHA256 e salt aleatório.
- O login rejeita usuários inexistentes, inativos ou com senha incorreta.