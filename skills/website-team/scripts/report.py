#!/usr/bin/env python3
"""Build the FACTS part of the final report from recorded data only (no opinions, no invented numbers).

  report.py --work WORK [--out facts.md]
"""
import argparse
import json
import sys
from pathlib import Path

from wt_common import counts

LABEL = {"pass": "نجح", "fail": "فشل", "needs_review": "يحتاج مراجعة", "not_run": "لم يُنفَّذ"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    w = Path(a.work)
    base = json.loads((w / "baseline.json").read_text(encoding="utf-8"))
    state = json.loads((w / "state.json").read_text(encoding="utf-8"))
    log = [json.loads(l) for l in (w / "decisions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    b, s = base["results"], state["results"]
    cb, cs = counts(b), counts(s)

    try:
        ver = json.loads((Path(__file__).resolve().parents[3] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, IndexError):
        ver = "غير معروف"
    L = ["## الحقائق المسجّلة (مولَّدة آلياً من نتائج الاختبارات)", "", f"- إصدار فريق الموقع: {ver}"]
    L.append(f"- الصفحات المختبَرة: {', '.join(state['pages'])}")
    L.append("- الحالة الأولى مأخوذة من 3 تشغيلات كاملة متطابقة. بعد ذلك، كل فحص تغيّرت نتيجته أُكِّد بثلاث تشغيلات "
             "(تشغيل كامل + تشغيلان موجّهان)، وكل فحص جديد شُغّل 3 مرات. أي نتيجة غير متطابقة تُعلَّم «يحتاج مراجعة».")
    L.append(f"- الإصدار النهائي: v{state['version']} (البداية v0)")
    L += ["", "| الحالة | البداية | النهاية |", "|---|---|---|"]
    for k in ("pass", "fail", "needs_review", "not_run"):
        L.append(f"| {LABEL[k]} | {cb.get(k, 0)} | {cs.get(k, 0)} |")
    added_ids = [e["targets"][0] for e in log if e["decision"] == "check-added"]
    new_other = [i for i in s if i not in b and i not in added_ids]
    if added_ids or new_other:
        L.append("")
        L.append(f"> عدد الفحوص في النهاية ({len(s)}) أكبر من البداية ({len(b)}): أُضيف {len(added_ids)} فحصاً سلوكياً مخصّصاً"
                 + (f"، وظهر {len(new_other)} فحصاً جديداً لعناصر أُضيفت للموقع" if new_other else "") + ".")
    retired = {e["targets"][0]: e for e in log if e["decision"] == "check-retired"}
    proven_later = [e["targets"][0] for e in log if e["decision"] == "check-added" and e["initial_status"] == "fail"
                    and e["targets"][0] not in retired]
    base_fail = [i for i, r in b.items() if r["status"] == "fail"]
    all_proven = base_fail + proven_later
    still = [i for i in all_proven if s.get(i, {}).get("status") != "pass"]
    L.append(f"- فحوص فشلت فعلاً خلال العمل: {len(all_proven)} "
             f"({len(base_fail)} في الفحص الأول + {len(proven_later)} فحوص أُضيفت لاحقاً وفشلت عند إضافتها)؛ "
             f"صار منها ناجحاً: {len(all_proven) - len(still)}، وبقي فاشلاً أو غير مؤكد: {len(still)}. "
             "(العدد يحسب الفحوص لا الأسباب: قد تفشل عدة فحوص بسبب خلل واحد.)")

    first_status = {e["targets"][0]: e["initial_status"] for e in log if e["decision"] == "check-added"}
    was = lambda i: b[i]["status"] if i in b else first_status.get(i)
    fixed = [i for i in s if s[i]["status"] == "pass" and was(i) in ("fail", "needs_review")]
    L += ["", f"### ما أُصلح وتحقَّق منه بالاختبار ({len(fixed)})",
          "(يشمل ما كان «فشل» أو «يحتاج مراجعة» وصار «نجح»)"]
    L += [f"- `{i}`: كان «{LABEL[was(i)]}» ← صار «نجح» ({s[i]['detail']})" for i in fixed] or ["- لا شيء"]

    open_ = [(i, r) for i, r in s.items() if r["status"] in ("fail", "needs_review")]
    L += ["", f"### ما زال مفتوحاً ({len(open_)})"]
    L += [f"- `{i}` [{LABEL[r['status']]}]: {r['detail']}" for i, r in open_] or ["- لا شيء"]

    nr = [(i, r) for i, r in s.items() if r["status"] == "not_run"]
    L += ["", f"### لم يُختبَر ({len(nr)})"]
    L += [f"- `{i}`: {r['detail']}" for i, r in nr]

    if state.get("backend_declared") or base.get("backend_declared"):
        pass
    acc = [e for e in log if e["decision"] == "accepted"]
    rej = [e for e in log if e["decision"] == "rejected"]
    reb = [e for e in log if e["decision"] == "rebaseline"]
    added = [e for e in log if e["decision"] == "check-added"]
    if added:
        L += ["", f"### فحوص سلوكية مخصّصة أُضيفت أثناء العمل ({len(added)})"]
        for e in added:
            cid = e["targets"][0]
            first = "فشل (المشكلة المشتبه بها ثبتت)" if e["initial_status"] == "fail" else "نجح (الشك لم يثبت، بقي كحارس)"
            now_ = LABEL[s[cid]["status"]] if cid in s else "غير موجود"
            L.append(f"- `{cid}`: {e['rationale']} — عند الإضافة: {first} ← الآن: {now_}")
    rej = [e for e in rej if e.get("kind") != "add-check"]
    L += ["", f"### سجل محاولات الإصلاح ({len(acc) + len(rej)} محاولة: {len(acc)} مقبولة، {len(rej)} مرفوضة)", "",
          "| # | المحاولة | النوع | القرار | السبب |", "|---|---|---|---|---|"]
    for n, e in enumerate(log, 1):
        d = {"accepted": "✅ قُبلت", "rejected": "❌ رُفضت", "check-added": "🧪 فحص أُضيف",
             "contract-amended": "🧪 شرط مسبق أُضيف لفحص", "check-retired": "🗄️ فحص سُحب",
             "rebaseline": "⚠️ تغيير خارج الحلقة (غير مُتحقَّق منه)"}[e["decision"]]
        reason = e["reason"].replace("|", "/")
        L.append(f"| {n} | {e['title']} | {e['kind']} | {d} | {reason} |")
    if retired:
        L += ["", f"### فحوص سُحبت لأنها كُتبت خطأ ({len(retired)})",
              "(لم تُحذف: تعريفها باقٍ في site-tests.json تحت retired، ولا تُحسب ضمن المشاكل المثبتة)"]
        for cid, e in retired.items():
            rep = e.get("replaced_by")
            rep_txt = (f"؛ البديل `{rep}` حالته الآن «{LABEL.get(s.get(rep, {}).get('status'), 'غير موجود')}»"
                       if rep else "؛ بموافقة المستخدم ودون بديل")
            L.append(f"- `{cid}` (كانت حالته «{LABEL[e['status_at_retirement']]}»): {e['rationale']}{rep_txt}")
    amend = [e for e in log if e["decision"] == "contract-amended"]
    if amend:
        L += ["", "### تعديلات على شروط الاختبار (مُعلنة)"]
        L += [f"- {e['title']}: {e['rationale']} ({e['reason']})" for e in amend]
    if reb:
        L += ["", f"> ⚠️ تم تعديل الموقع خارج حلقة التحقق {len(reb)} مرة. هذه التعديلات لم يتحقق منها النظام كإصلاحات، "
                  "وأُعيد قياس الحالة بعدها فقط."]
    design = [e for e in acc if e["kind"] == "design"]
    if design:
        L += ["", "### تعديلات تصميمية قُبلت لأنها لم تكسر شيئاً، لكن فائدتها غير مُثبتة بالاختبار"]
        L += [f"- {e['title']}" for e in design]
    L += ["", "> النجاح في هذه الاختبارات لا يعني أن الموقع آمن بالكامل، ولا يضمن نتائج تجارية "
              "(زيارات أو مبيعات). هذه تحتاج قياساً بعد الإطلاق."]
    text = "\n".join(L) + "\n"
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
