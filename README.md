# PlayersSearchProject

Скрипт заполняет `supercell_id` в таблице Supabase `players_in_progress`, находя Supercell ID игроков в эмуляторе Brawl Stars на ПК.

## Алгоритм (как в ТЗ)

1. Берём из Supabase `players_in_progress` строки, где `supercell_id IS NULL`.
2. Для каждой строки:
   - Открываем вкладку **Клуб**.
   - Вставляем `club_tag` игрока в поиск клуба.
   - Выбираем **первый** клуб в результатах.
   - Ищем игрока по `name` в списке участников (OCR + скролл вниз при необходимости) и открываем его профиль.
   - Считываем Supercell ID из чёрной рамки ближе к левому верхнему углу профиля, сохраняя регистр букв.
   - Возвращаемся на главный экран (сначала шаблон `TEMPLATE_HOME_BUTTON`, затем координаты).
3. Обновляем строку в Supabase, записывая найденное значение в `supercell_id`.

## Требования

- Windows
- Запущенный эмулятор с Brawl Stars (окно должно быть видно и доступно для кликов)
- Установленный ADB **не обязателен** (используется режим `pyautogui`)
- Для OCR: по умолчанию Tesseract OCR в `PATH` (или `TESSERACT_CMD`); опционально можно включить PaddleOCR через `OCR_ENGINE=paddle` или `OCR_ENGINE=auto`

## Установка

1. Активируйте venv.
2. Установите зависимости:
   - `pip install -r requirements.txt`
   - опционально для PaddleOCR: `pip install -r requirements-ocr-paddle.txt` (файл ставит CPU runtime `paddlepaddle`; для GPU/CUDA замените его на подходящий пакет PaddlePaddle по официальной инструкции).
3. Создайте `.env` (пример ниже).

## Настройка `.env`

```env
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_TABLE=players_in_progress

# Названия колонок в таблице (если у вас отличаются)
COL_ID=id
COL_NAME=name
COL_SUPERCELL_ID=supercell_id
COL_CLUB_TAG=club_tag

# OCR
# OCR_ENGINE: tesseract (по умолчанию), paddle или auto (PaddleOCR с fallback на Tesseract)
OCR_ENGINE=tesseract
TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe
OCR_LANG=rus+eng

# Шаблоны (PNG) для поиска элементов по картинке (надежнее OCR для стилизованного текста/иконок)
# Путь можно задавать относительный от корня проекта.
TEMPLATE_CLUB_TAB=templates\\club.png
TEMPLATE_SEARCH_BOX=templates\\club_search_box.png
TEMPLATE_SEARCH_BUTTON=templates\\search_button.png
TEMPLATE_FIRST_RESULT=templates\\first_club_result.png
TEMPLATE_HOME_BUTTON=templates\\home_button.png

# Горячая клавиша переключения раскладки (Windows). Примеры: alt+shift, win+space.
LAYOUT_SWITCH_HOTKEY=alt+shift

# Заголовок окна эмулятора (поиск по подстроке, без учета регистра). Примеры: BlueStacks, LDPlayer, Nox.
EMULATOR_WINDOW_TITLE=BlueStacks

# Автоматизация (координаты в пикселях; см. режим calibrate)
COORD_CLUB_TAB_X=100
COORD_CLUB_TAB_Y=100
COORD_SEARCH_BOX_X=200
COORD_SEARCH_BOX_Y=200
COORD_FIRST_RESULT_X=300
COORD_FIRST_RESULT_Y=300
COORD_BACK_HOME_X=1800
COORD_BACK_HOME_Y=120

# Область на экране, где читается ник и Supercell ID (left, top, width, height)
ROI_MEMBER_LIST=200,250,1400,750
ROI_PLAYER_CARD=120,140,650,160
```

Подсказки по `SUPABASE_URL`/ключу:
- `SUPABASE_URL` должен быть **Project URL** вида `https://xxxx.supabase.co` (не `.../rest/v1`).
- `SUPABASE_SERVICE_ROLE_KEY` — ключ **service_role** из Supabase Dashboard → Settings → API → Project API keys (обычно начинается с `eyJ...`).
- Проверка, что `.env` реально подхватился: `python -m players_search debug-env`.

## Запуск

- Проверка без записи в БД:
  - `python -m players_search run --dry-run --limit 10`
- Заполнение `supercell_id`:
  - `python -m players_search run --limit 50`
- Калибровка координат (печатает текущие координаты курсора раз в 0.5с):
  - `python -m players_search calibrate`
- Зафиксировать/проверить размер окна эмулятора (для стабильных ROI/COORD):
  - `python -m players_search lock-window --width 1920 --height 1080`
  - `python -m players_search lock-window --width 1920 --height 1080 --strict`
- Если не знаете заголовок окна эмулятора:
  - `python -m players_search list-windows`
- Пошаговая проверка отдельных действий:
  - Команда `step` всегда выполняет все шаги **с начала до указанного**.
  - `python -m players_search step club_tab` (только открывает вкладку **Клуб**)
  - `python -m players_search step search_club --club-tag "#2Q2CQYPC8"` (выполнит `club_tab` + `search_club`)
  - `python -m players_search step open_first --club-tag "#2Q2CQYPC8"` (выполнит `club_tab` + `search_club` + `open_first`)
  - `python -m players_search step find_player --club-tag "#2Q2CQYPC8" --player-name "Nickname"` (выполнит поиск игрока в списке участников и откроет его профиль)
  - `python -m players_search step read_supercell_id --club-tag "#2Q2CQYPC8" --player-name "Nickname"` (выполнит шаги до профиля и считает Supercell ID из чёрной рамки ближе к левому верхнему углу)
  - `python -m players_search step home --club-tag "#2Q2CQYPC8" --player-name "Nickname"` (выполнит шаги до считывания Supercell ID и вернётся на начальный экран)
- Проверка OCR-поиска элемента по тексту (сохранит скриншот и скриншот с рамкой):
  - `python -m players_search probe-text --text "Клуб"`
  - `python -m players_search probe-text --text "Клуб" --click`
  - `python -m players_search probe-text --text "Искать" --dump-ocr`
- Проверка поиска элемента по картинке (template matching):
  - `python -m players_search probe-template --template templates\\club.png`
  - `python -m players_search probe-template --template templates\\club.png --click`

## Важно

Алгоритм делает клики/скриншоты **только относительно окна эмулятора** (по `EMULATOR_WINDOW_TITLE`). Координаты `COORD_*` и области `ROI_*` задаются **в координатах окна**, поэтому их нужно один раз откалибровать под ваш эмулятор/разрешение.
Если окно эмулятора было свёрнуто, скрипт попытается автоматически восстановить его (но всё равно окно должно быть реально отрисовано на экране — OCR берёт картинку с экрана).

Почему всё равно могут понадобиться координаты:
- OCR по “кнопкам” в Brawl Stars иногда нестабилен из-за шрифтов/анимаций. Поэтому сейчас реализовано: **сначала OCR-попытка**, затем **fallback на координаты**.
- Для стилизованных кнопок (например “КЛУБ”) лучше работает template matching по PNG-шаблону: задайте `TEMPLATE_CLUB_TAB` и положите файл (например) в `templates\\club.png`.
- Поиск игрока на шаге `find_player` только открывает профиль: читает область `ROI_MEMBER_LIST`, группирует OCR-слова по строкам, сравнивает их с `--player-name`, при промахе повторяет OCR несколькими режимами/предобработками и прокручивает список циклически (вниз до конца, затем вверх и обратно) с ограничением по числу циклов. Считывание Supercell ID вынесено в шаг `read_supercell_id`: он ищет чёрную рамку ближе к левому верхнему углу в `ROI_PLAYER_CARD`, ждёт появления ID после открытия профиля и сохраняет регистр букв. При `OCR_ENGINE=paddle` используется PaddleOCR; при `OCR_ENGINE=auto` PaddleOCR пробуется первым, а Tesseract остаётся fallback.

Про ввод `club_tag`:
- Ввод `club_tag` в поле поиска клуба делается прямым набором физическими клавишами: скрипт сначала читает текущую раскладку окна и переключает её через `LAYOUT_SWITCH_HOTKEY` только если она не EN, затем вводит `#` как `Shift+3`, буквы — lowercase-клавишами, цифры — цифровыми клавишами. Прямое WinAPI-переключение раскладки не используется; если прямой набор недоступен, используется fallback через буфер обмена (`Ctrl+V`).
- После ввода скрипт нажимает Enter (закрыть клавиатуру), затем нажимает кнопку поиска по шаблону `TEMPLATE_SEARCH_BUTTON` (если задано). Если шаблон не задан/не найден — пробует OCR `Искать`/`Search`, иначе жмёт Enter ещё раз. Возврат домой сначала ищет `TEMPLATE_HOME_BUTTON`, затем использует координаты `COORD_BACK_HOME_*`.
