# -*- coding: utf-8 -*-
"""Проверка перед действием: напоминание при записи стартера без фактового блока.

Подключение в Claude Code — фрагмент для ~/.claude/settings.json (раздел hooks):

  "PreToolUse": [
    {
      "matcher": "Write|Edit|MultiEdit",
      "hooks": [
        {
          "type": "command",
          "command": "py -3.14 \"<путь к набору>/templates/hooks/starter-facts-guard.py\"",
          "timeout": 5
        }
      ]
    }
  ]

Срабатывает на запись файлов с именами СТАРТЕР*, *starter*, *handoff*: если
в записываемом содержимом нет маркера «handoff-facts» — печатает напоминание.
Не блокирует (выход всегда 0). Урок надёжности: stdin читать БИНАРНО —
текстовый stdin на Windows декодируется системной кодировкой и молча ломает
кириллицу в путях, а «except» превращает защиту в тишину.
"""
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

# Матчер имён файлов: слова-варианты нужны здесь по назначению (ловим и старые имена)
NAME_RX = re.compile(r"(СТАРТЕР|СТАРТ[_-]|starter|hand-?off|хэндофф|хендофф)", re.I)
MARKER = "handoff-facts"

try:
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    if not NAME_RX.search(path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]):
        sys.exit(0)
    content = tool_input.get("content") or tool_input.get("new_string") or ""
    if MARKER in content:
        sys.exit(0)
    print("=" * 68)
    print("[starter-facts] Пишешь стартер сессии БЕЗ фактового блока.")
    print("Фактовую часть НЕ писать руками — сгенерировать и вклеить:")
    print("  py -3.14 <набор>/tools/handoff-facts.py <репо> --last 15")
    print("Рассказ — поверх фактов. «✅ прошлой сессии» = непроверенное утверждение.")
    print("=" * 68)
except Exception as e:
    # Не ломаем поток инструмента, но и не молчим — тишина превращает защиту в дыру
    print(f"[starter-facts] проверка не отработала: {type(e).__name__}: {e}", file=sys.stderr)
sys.exit(0)
