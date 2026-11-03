import json

with open("backlog.json", "r", encoding="utf-8") as f:
    projects = json.load(f)
    
print("--- СТАРТ СКОРИНГА БЭКЛОГА ---")

# Список обязательных полей
REQUIRED_FIELDS = ["id", "title", "stack_required", "reach", "impact", "confidence", "effort"]

valid_projects = []

for h in projects:
    # 1. Проверяем, все ли обязательные поля вообще есть
    missing_fields = [field for field in REQUIRED_FIELDS if field not in h]
    if missing_fields:
        h_id = h.get("id", "Неизвестно")
        print(f"Ошибка: В гипотезе ID {h_id} отсутствуют поля: {', '.join(missing_fields)}")
        continue
        
    # 2. Проверяем типы данных (reach, impact, confidence, effort должны быть числами)
    # isinstance(x, (int, float)) проверяет, является ли значение целым или дробным числом
    numeric_errors = []
    for field in ["reach", "impact", "confidence", "effort"]:
        if not isinstance(h[field], (int, float)):
            numeric_errors.append(field)
            
    if numeric_errors:
        print(f"Ошибка: В гипотезе ID {h['id']} поля {', '.join(numeric_errors)} должны быть числами, а не текстом!")
        continue

    # 3. Простая валидация стека
    if h["stack_required"] not in ["B", "F", "BaF"]:
        print(f"Пропуск: Неверный стек в гипотезе {h['id']}")
        continue
        
    # 4. Защита от деления на ноль
    if h["effort"] == 0:
        print(f"Пропуск: Трудозатраты (effort) для гипотезы {h['id']} равны 0")
        continue
        
    # Вычисление формулы RICE
    rice_score = (h["reach"] * h["impact"] * h["confidence"]) / h["effort"]
    h["rice_score"] = round(rice_score, 1)
    
    valid_projects.append(h)

# Сортировка и вывод результатов
valid_projects.sort(key=lambda x: x["rice_score"], reverse=True)

print("\n--- ПРИОРИТЕТИЗИРОВАННЫЙ БЭКЛОГ ---")
for idx, h in enumerate(valid_projects, 1):
    print(f"{idx}. [{h['stack_required']}] {h['title']} -> RICE Score: {h['rice_score']}")

# Сохраняем результат в новый JSON-ФАЙЛ
with open("scored_backlog.json", "w", encoding="utf-8") as f_json:
    json.dump(valid_projects, f_json, ensure_ascii=False, indent=2)

print("\n ✅ Файл 'scored_backlog.json' успешно сохранен и готов к отправке в ИИ.")
