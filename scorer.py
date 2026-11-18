import json
import os

def run_scoring(input_file="backlog.json", output_file="scored_backlog.json"):
    if not os.path.exists(input_file):
        return [], ["Файл backlog.json не найден."]

    with open(input_file, "r", encoding="utf-8") as f:
        try:
            projects = json.load(f)
        except json.JSONDecodeError:
            return [], ["Ошибка чтения JSON в файле backlog.json."]

    if not projects:
        return [], ["Бэклог пуст. Сначала добавьте хотя бы одну фичу."]

    REQUIRED_FIELDS = ["id", "title", "stack_required", "reach", "impact", "confidence", "effort"]
    valid_projects = []
    errors = []

    for h in projects:
        h_id = h.get("id", "Неизвестно")

        # 1. Проверка наличия обязательных полей
        missing_fields = [field for field in REQUIRED_FIELDS if field not in h]
        if missing_fields:
            errors.append(f"ID {h_id}: отсутствуют поля {', '.join(missing_fields)}")
            continue

        # 2. Проверка типов данных
        numeric_errors = [
            field for field in ["reach", "impact", "confidence", "effort"]
            if not isinstance(h[field], (int, float)) or isinstance(h[field], bool)
        ]
        if numeric_errors:
            errors.append(f"ID {h_id}: поля {', '.join(numeric_errors)} должны быть числами")
            continue

        # 3. Валидация стека
        if h["stack_required"] not in ["B", "F", "BaF"]:
            errors.append(f"ID {h_id}: неверный стек ({h['stack_required']})")
            continue

        # 4. Защита от деления на ноль
        if h["effort"] <= 0:
            errors.append(f"ID {h_id}: effort должен быть больше 0")
            continue

        # Вычисление формулы RICE
        rice_score = (h["reach"] * h["impact"] * h["confidence"]) / h["effort"]
        h["rice_score"] = round(rice_score, 1)
        valid_projects.append(h)

    # Сортировка по убыванию RICE Score
    valid_projects.sort(key=lambda x: x["rice_score"], reverse=True)

    # Сохраняем результат в scored_backlog.json
    with open(output_file, "w", encoding="utf-8") as f_json:
        json.dump(valid_projects, f_json, ensure_ascii=False, indent=2)

    return valid_projects, errors

# Позволяет запускать scorer.py и напрямую в терминале, как раньше
if __name__ == "__main__":
    scored, errs = run_scoring()
    for e in errs:
        print("Ошибка:", e)
    for idx, h in enumerate(scored, 1):
        print(f"{idx}. [{h['stack_required']}] {h['title']} -> RICE Score: {h['rice_score']}")
