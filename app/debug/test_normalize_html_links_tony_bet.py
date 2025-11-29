from app.plugins.posts_watch_listener import _normalize_html_links
from app.services.html_match import exact_html_equal


HTML_DB = """
<b>⚡️ТАСС: Жители города Самара массово увольняются со своих рабочих мест</b>

Рост увольнений составил 150% — это более 38 тысяч людей за полгода. Но причина раскрылась совсем недавно

<b>Слова жителя:</b> <i>"Бывший коллега</i> <i>скинул канал </i><a href="https://t.me/+6b77wlU_D7U5ZDg6"><i>TONY BET</i></a><i> </i>—<i> говорит, зарабатываю 12-15 тыс ₽ в день по прогнозам оттуда, не хочу обратно в офис"</i>

По данным, всё больше жителей отказываются от найма, так как доход на спортивных прогнозах <b>за неделю</b> перекрывает среднюю месячную зарплату

<b>Если вы давно хотели увеличить доход и сменить место работы, то заходите: </b>https://t.me/+6b77wlU_D7U5ZDg6
""".strip()


HTML_CHANNEL = """
<b>⚡️ТАСС: Жители города Самара массово увольняются со своих рабочих мест</b>

Рост увольнений составил 150% — это более 38 тысяч людей за полгода. Но причина раскрылась совсем недавно

<b>Слова жителя:</b> <i>"Бывший коллега</i> <i>скинул канал </i><a href="https://t.me/+6b77wlU_D7U5ZDg6"><i>TONY BET</i></a><i> </i>—<i> говорит, зарабатываю 12-15 тыс ₽ в день по прогнозам оттуда, не хочу обратно в офис"</i>

По данным, всё больше жителей отказываются от найма, так как доход на спортивных прогнозах <b>за неделю</b> перекрывает среднюю месячную зарплату

<b>Если вы давно хотели увеличить доход и сменить место работы, то заходите: </b><a href="https://t.me/+6b77wlU_D7U5ZDg6">https://t.me/+6b77wlU_D7U5ZDg6</a>
""".strip()


def main():
    print("=== RAW ===")
    print("DB HTML:")
    print(HTML_DB)
    print("\nCHANNEL HTML:")
    print(HTML_CHANNEL)

    norm_db = _normalize_html_links(HTML_DB)
    norm_ch = _normalize_html_links(HTML_CHANNEL)

    print("\n=== NORMALIZED ===")
    print("DB HTML NORM:")
    print(norm_db)
    print("\nCHANNEL HTML NORM:")
    print(norm_ch)

    print("\n=== COMPARISON ===")
    print("norm equal (==):", norm_db == norm_ch)
    try:
        print("exact_html_equal(norm_db, norm_ch):", exact_html_equal(norm_db, norm_ch))
    except Exception as e:
        print("exact_html_equal raised:", repr(e))


if __name__ == "__main__":
    main()