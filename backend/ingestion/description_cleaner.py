"""
Модуль для очистки описаний видео с YouTube.
Исключает хештеги, ссылки (URL), призывы к действию (Wishlist / Subscribe / Follow),
заголовки соцсетей, разделители и лишний текст вокруг ссылок.
"""
import re
import unicodedata
from difflib import SequenceMatcher

# Декоративные символы (эмодзи, стрелки, точки-разделители), которыми
# авторы часто обрамляют CTA-строки — например "▶ MY TWITTER" или
# "🟢Wishlist on Xbox:". Не срезав их сначала, ключевые слова вроде
# "wishlist"/"twitter" в LINE_NOISE_REGEX ниже никогда не совпадают, так
# как первый символ строки — не буква, а декоративный символ, из-за чего
# якорь `^\s*keyword` не срабатывает.
_DECORATIVE_EXTRA_CHARS = set("-=_*~•·►▶➤➔")


def _is_decorative_char(ch: str) -> bool:
    if ch.isspace() or ch in _DECORATIVE_EXTRA_CHARS:
        return True
    category = unicodedata.category(ch)
    # So/Sk — символьные категории Unicode, покрывающие почти все эмодзи,
    # дингбаты и стрелки; Mn — небазовые модификаторы (например, вариативный
    # селектор U+FE0F в "➡️"), сами по себе невидимые и не несущие смысла.
    return category in ("So", "Sk", "Mn")


def _strip_decorative_edges(line: str) -> str:
    start = 0
    while start < len(line) and _is_decorative_char(line[start]):
        start += 1
    end = len(line)
    while end > start and _is_decorative_char(line[end - 1]):
        end -= 1
    return line[start:end]

# Регулярки для удаления ссылок (без ложных срабатываний на слова типа itch.io в предложениях)
URL_REGEX = re.compile(
    r"https?://\S+|www\.\S+|(?:store\.steampowered\.com|steampowered\.com|discord\.gg|bit\.ly|youtu\.be|youtube\.com|x\.com|twitter\.com|instagram\.com|tiktok\.com|reddit\.com|facebook\.com|patreon\.com|kickstarter\.com)\S*",
    re.IGNORECASE
)
HASHTAG_REGEX = re.compile(r"#\w+", re.UNICODE)

# Фразы-призывы внутри предложений (например: "Wishlist now on Steam! - https://...")
INLINE_CTA_REGEX = re.compile(
    r"(?:[-|—•\s]*\b(?:wishlist now|wishlist here|wishlist on steam|add to wishlist|check out our|follow us|join our|available now on|out now on|get it on|buy now|link in bio)[^.!;\n]*[!.]?)",
    re.IGNORECASE
)

# Ключевые слова для удаления целых строк-заголовков соцсетей/ссылок/авторов и CTA
LINE_NOISE_PATTERNS = [
    r"^\s*(?:wishlist|steam|playstation|xbox|nintendo|switch|epic games|gog|itch\.io|apple|android)\s*:?.*$",
    # "follow" broadened to match anything after it (was `follow (?:us )?
    # (?:on )?` — required "us"/"on" to come *immediately* after "follow",
    # so it missed "Follow Team17 on socials to stay up to date", where a
    # name is inserted in between). In a game-trailer description, a line
    # that opens with "follow" is essentially always this same CTA.
    r"^\s*(?:social(?:s| media)?|links?|follow\b.*|join (?:us )?(?:on )?|connect (?:with us)?|community)\s*:?.*$",
    r"^\s*(?:twitter|facebook|reddit|discord|instagram|tiktok|youtube|tumblr|patreon|kickstarter|website|blog|store|shop|twitch)\b\s*:?.*$",
    # combined platform labels ("X/Twitter") that don't start with any
    # single keyword above
    r"^\s*x\s*/\s*twitter\s*:?.*$",
    # "Our Twitter:", "Our Discord Server:", "My Instagram" — a
    # possessive prefix in front of the platform name, which the plain
    # keyword-anchored patterns above don't cover since the line doesn't
    # *start* with the platform name itself.
    r"^\s*(?:our|my)\s+(?:twitter|x|discord|instagram|tiktok|youtube|facebook|reddit|twitch|patreon|kickstarter|website|steam)\b.*$",
    r"^\s*(?:developer|publisher|music|trailer|edited|directed|soundtrack|audio|credit|art)(?:\s+(?:by|is by|from))?\s*:?.*$",
    r"^\s*(?:also,?\s*|please,?\s*|and,?\s*)*(?:for more (?:details|info|information)|keep up with|don't forget to|like and subscribe|subscribe|be sure to|check out).*$",
    r"^\s*(?:also,?\s*|please,?\s*|and,?\s*)*(?:add .* to your wishlist|wishlist .* now|wishlist .* on|wishlist .* to support).*$",
    r"^\s*support\s+(?:the\s+team|us|the\s+developers?|the\s+devs?)\b.*$",
    r"^\s*faq\s*:?.*$",
    r"^\s*game\s+link\s*\d*\s*:?.*$",
    r"^\s*[-=_*#~]{3,}\s*$",  # Разделители --- === ***
    r"^\s*@\w+.*$",          # Упоминания аккаунтов @BrightboneMusic
]

LINE_NOISE_REGEX = re.compile(
    "|".join(f"(?:{p})" for p in LINE_NOISE_PATTERNS),
    re.IGNORECASE
)


def _is_similar_title(line: str, title: str) -> bool:
    if not line or not title:
        return False
    norm_line = re.sub(r"[^\w\s]", "", line).lower().strip()
    norm_title = re.sub(r"[^\w\s]", "", title).lower().strip()
    if not norm_line or not norm_title:
        return False
    ratio = SequenceMatcher(None, norm_line, norm_title).ratio()
    return ratio >= 0.65 or norm_line == norm_title or norm_line in norm_title or norm_title in norm_line


def clean_video_description(raw_text: str, title: str = "") -> str:
    """
    Очищает описание видео, возвращая только смысловую часть (синопсис/сюжет/особенности игры).
    Если передан `title`, также удаляет первую строку, если она дублирует название видео.
    """
    if not raw_text:
        return ""

    lines = raw_text.splitlines()
    cleaned_lines = []

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        # Срезаем декоративные символы по краям (эмодзи, стрелки, точки),
        # иначе ключевые слова ниже не совпадут с "🟢Wishlist on Xbox:"
        line_str = _strip_decorative_edges(line_str)
        if not line_str:
            continue

        # 1. Если вся строка похожа на заголовок соцсетей, ссылку или призыв — пропускаем
        if LINE_NOISE_REGEX.match(line_str):
            continue

        # 2. Удаляем хештеги
        line_str = HASHTAG_REGEX.sub("", line_str)

        # 3. Если в строке была ссылка — удаляем её и призыв вокруг
        if URL_REGEX.search(line_str):
            line_str = URL_REGEX.sub("", line_str)
            line_str = INLINE_CTA_REGEX.sub("", line_str)

        # 4. Очищаем висячие знаки препинания и разделители, оставшиеся после удаления ссылок
        line_str = re.sub(r"\s+[-—–|•:*]+\s*$", "", line_str)
        line_str = re.sub(r"^\s*[-—–|•:*]+\s+", "", line_str)
        line_str = re.sub(r"\s{2,}", " ", line_str).strip()

        # Если после очистки строка стала пустой или слишком короткой (мусор из 1-2 символов)
        if len(line_str) < 3 and not line_str.isalnum():
            continue

        # 5. Исключаем первую строку, если автор просто скопировал в неё заголовок видео
        if not cleaned_lines and _is_similar_title(line_str, title):
            continue

        cleaned_lines.append(line_str)

    # Убираем дублирующиеся строки и объединяем абзацы
    result_blocks = []
    for line in cleaned_lines:
        if not result_blocks:
            result_blocks.append(line)
        else:
            if line.lower() != result_blocks[-1].lower():
                result_blocks.append(line)

    return "\n\n".join(result_blocks).strip()
