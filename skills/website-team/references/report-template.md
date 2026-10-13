# Final report template (write REPORT.md in the user's language)

```
# تقرير فريق الموقع: <project name>

## الخلاصة (3–5 أسطر)
- ما الموقع وما هدفه (من brief.md).
- النتيجة بالأرقام من facts.md فقط: الفحوص الفاشلة X ← Y، والإصدار النهائي vN.
- أهم ما زال مفتوحاً، وأهم ما لم يُختبر.

## نقاط القوة التي حافظنا عليها
- من committee/chair.md (keep) ومن advocate.md، كل نقطة مع السبب.

## ما أصلحناه
- لكل إصلاح مقبول: المشكلة، والتعديل، والفحص الذي أثبته (معرّف الفحص).
- التعديلات التصميمية المقبولة تُذكر بوضوح أن فائدتها رأي غير مُثبت بالاختبار.

## ما رُفض ولماذا
- المحاولات المرفوضة وأسبابها (تراجع، لم يُصلح الهدف، تجاوز الحد...).

## ما زال مفتوحاً
- كل فحص fail أو needs_review، وكل بند من الخطة لم يُنفَّذ (تجاوز الحد).

## اقتراحات تحتاج موافقتك
- بنود الخطة التي تغيّر المحتوى أو تحذف شيئاً: لم تُنفَّذ، وكل بند بسطر واحد مع سببه.

## هل طُبّقت التعديلات على موقعك؟
- نتيجة `sync_site.py apply` حرفياً (الملفات التي تغيّرت)، أو سبب عدم التطبيق.

## افتراضات يجب حسمها قبل الإطلاق
- مثل: خادم النماذج محاكى في الاختبار (site-tests.json)، صور مؤقتة، نصوص مقترحة.

## ما لم يُختبر
- كل بنود not_run، والوظائف المطلوبة التي لا يغطيها أي فحص (من inspector.md).

## الخطوات التالية المقترحة
- 3 خطوات كحد أقصى، مرتبة.

---
<الصق محتوى work/facts.md هنا دون أي تعديل>
```

Rules: no number may appear in the narrative unless it is in facts.md. Count failing checks as checks, and say when several checks share one cause. A change is 'fixed' only with a passing check id; changes without a covering check go under 'ما لم يُختبر'. If no attempt was rejected in this project, say so plainly (the rejection path was not exercised here). Never write "the site is secure", "bug-free" or "will increase sales". Say explicitly that passing these tests does not guarantee business results.
