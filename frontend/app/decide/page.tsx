import AskBar from "@/components/AskBar";

export default function Decide() {
  return (
    <div className="space-y-8">
      <header>
        <p className="label">New decision</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">What should you do?</h1>
        <p className="mt-2 max-w-2xl text-muted">
          Describe the goal with any budget, deadline or preferences. DecisionOS researches live sources, compares options
          against your priorities, explains the winner and turns it into a plan. Add an image to identify a product and
          compare its prices.
        </p>
      </header>
      <AskBar showExamples />
      <div className="grid gap-4 md:grid-cols-3">
        {[
          ["Understand", "Goal, hard constraints (budget, deadline, distance) and soft preferences are extracted."],
          ["Research → Evidence", "Searches across shopping, maps, flights, news, scholar and video sources; results are de-duplicated and cross-verified."],
          ["Decide → Plan", "Weighted scoring by your priorities, a plain-English why, what-if scenarios, then tasks, calendar and reminders."],
        ].map(([t, d]) => (
          <div key={t} className="card p-4">
            <p className="font-medium">{t}</p>
            <p className="mt-1 text-sm text-muted">{d}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
