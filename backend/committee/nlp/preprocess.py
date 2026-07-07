"""Small text-cleanup helpers shared by any agent that feeds raw headlines
into an LLM prompt."""


def clean_headlines(headlines: list[str], max_items: int = 8) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for headline in headlines:
        text = headline.strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
        if len(cleaned) >= max_items:
            break
    return cleaned
