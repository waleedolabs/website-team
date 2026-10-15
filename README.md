# Website Team

A Claude Code plugin that reviews a website you already have, **only when you ask for it by name**.
It finds problems with real browser tests plus a careful code review, **tells you what it found and what it plans to change, and changes nothing until you agree**. After you approve it fixes, re-tests to prove the fixes, and gives a short summary.

> **Status: beta.** Tested on small test sites and on one real project (Windows). See [Honest limits](#honest-limits).

## Install

```
/plugin install website-team --marketplace waleedolabs/website-team
```

Requirements: Python 3 and Playwright with Chromium (`pip install playwright && python -m playwright install chromium`). No API key.

## Use

After Claude has built or edited your site, say:

- **"خلي فريق الموقع يراجع الموقع"** / "have the website team review the site" → fast review.
- **"…فريق الموقع الكامل…"** / "…the full website team…" → same, plus an independent critic (design, clarity, mobile, trust) and the strengths worth protecting.

What happens, in order:

1. **Discover (read-only):** a browser scan, a map of the site (which button runs which function, where each form sends), and a code review. The originals are backed up in a hidden `.website-team` folder.
2. **One plan message:** proven by tests / found by reading the code / suggestions that need your approval (any change to texts, prices, contact details, or removing anything).
3. **It waits for your answer.** Nothing in your site is touched before that.
4. **After you agree:** fixes in your real files (no commit, no push), re-test, and automatic restore of any file the edit broke.
5. **A summary of at most 6 lines.**

Guarantees: it never changes your texts, prices or contact details on its own, never deletes links, buttons or sections, and never leaves a form that claims "sent" when nothing is sent. Delete `.website-team` before you upload the site.

## What it checks

Per page: load errors, JavaScript errors, buttons that do nothing or throw, forms (flags fake "thank you" forms that send nothing), broken links and anchors, image alt text, contrast (WCAG AA), field labels, `lang`, `dir="rtl"`, `charset`, `title`, viewport, horizontal scrolling at 375 px. The code review looks for logic the browser cannot see (wrong calculations, filters, sorting, date handling, phone/WhatsApp link formats, features unusable on mobile).

## Measured (same grader, plain Claude as baseline)

| | usage vs plain Claude | time | planted defects fixed (blind site, 10) |
|---|---|---|---|
| plain Claude | 1x | ~25 s | 10/10 |
| fast review | ~1.2–1.3x | ~35–60 s | 10/10 |
| full review (light) | ~1.7–1.8x | ~45–65 s | 10/10 |

## Honest limits

- **It does not find more defects than plain Claude** on small sites. What it adds: browser proof after each change, automatic restore, no deletions, no false "sent" messages, and a plan you approve first.
- Static sites (HTML/CSS/JS). It does not run Node/PHP servers. Not covered: performance, security audits, other browsers, real back ends, external links.
- Benchmarks used small test sites; only one real project and one Windows machine so far. Large and framework-built sites are untested.
- The site map is static analysis: handlers wired at run time can show as "NO HANDLER FOUND" (a false alarm the reviewer is told to check).
- Full mode was measured once per site; usage figures are totals including subagents from single runs.

## Development

`skills/website-team/scripts/` has the scanner (`scan.py`), the site map (`sitemap.py`), the test runner and self-tests (`scan_selftest.py`, `selftest.py`, `selftest_loop.py`). `dev/build.sh` builds a `.plugin` file. See `CHANGELOG.md`.

## License

MIT © 2026 Waleed Arnaout

---

# فريق الموقع (عربي)

إضافة لـ Claude Code بتراجع موقعك الجاهز، **بس لما تطلبها بالاسم**. بتكتشف المشاكل بفحص متصفح حقيقي وقراءة كود، **وبتبعتلك رسالة بالموجود وشو ناوية تعمل، وما بتغيّر شي قبل موافقتك**. بعد الموافقة بتصلّح، وبتعيد الفحص لتثبت، وبتعطيك ملخص قصير.

> **نسخة تجريبية (beta).** مجرّبة على مواقع اختبار صغيرة وعلى مشروع حقيقي واحد (ويندوز).

## التثبيت

```
/plugin install website-team --marketplace waleedolabs/website-team
```

المتطلبات: Python 3 وPlaywright مع Chromium (`pip install playwright && python -m playwright install chromium`). ما في حاجة لمفتاح API.

## الاستخدام

- **«خلي فريق الموقع يراجع الموقع»** ← مراجعة سريعة.
- **«خلي فريق الموقع الكامل يراجع الموقع»** ← نفسها، مع ناقد مستقل (تصميم، وضوح، موبايل، ثقة) ونقاط القوة اللي لازم تنحمى.

الترتيب: اكتشاف بدون تغيير (فحص + خريطة للموقع + قراءة كود، ونسخة احتياطية بمجلد مخفي `.website-team`) ← رسالة وحدة بالخطة ← بتنتظر جوابك ← بعد موافقتك بتصلّح على ملفاتك مباشرة (بدون commit ولا رفع) وبتعيد الفحص وبترجّع أي ملف انكسر ← ملخص ٦ أسطر.

الضمانات: ما بتغيّر نصوصك ولا أسعارك ولا أرقام التواصل من حالها، ما بتحذف روابط ولا أزرار ولا أقسام، وما بتترك فورم بيقول «تم الإرسال» وهو ما بعت شي. احذف مجلد `.website-team` قبل ما ترفع الموقع.

## بصراحة

- **ما بتلاقي أخطاء أكتر من Claude العادي** على المواقع الصغيرة. اللي بتضيفه: إثبات بالمتصفح بعد كل تعديل، وإرجاع تلقائي، وبدون حذف أو ادّعاءات كاذبة، وخطة بتوافق عليها أول.
- للمواقع الثابتة (HTML/CSS/JS). ما بتغطي: الأداء، الأمان، متصفحات تانية، خوادم حقيقية، روابط خارجية.
- جُرّبت على مواقع صغيرة ومشروع حقيقي واحد. المواقع الكبيرة أو المبنية بأطر عمل ما انجرّبت.

## الترخيص

MIT © 2026 Waleed Arnaout
