# API Models and Limits

## Available Models and Rate Limits

| Model | Requests per Minute | Requests per Day| Tokens per Minute | Tokens per Day |
|---|---|---|---|---|
| `openai/gpt-oss-120b` | 30 | 1K | 8K | 200K |
| `openai/gpt-oss-20b` | 30 | 1K | 8K | 200K |

## Usage Assignments

- **Chatbot:** `openai/gpt-oss-20b`
- **Resume Parsing:** `openai/gpt-oss-120b`

*Note: Provide `GROQ_CHATBOT_API_KEY` and `GROQ_RESUME_PARSER_API_KEY` in the `.env` file.*
