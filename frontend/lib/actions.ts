import { api, Intervention } from "./api";

type Router = { push: (href: string) => void };

/** Execute an intervention action: backend side-effects + client navigation. */
export async function runAction(iv: Intervention, action: Intervention["actions"][number], router: Router) {
  const res = await api<any>(`/api/interventions/${iv.id}/respond`, { method: "POST", json: { action } });
  if (action.type === "open_decision" && action.decision_id) router.push(`/decisions/${action.decision_id}`);
  if (action.type === "refresh_decision" && res?.decision?.id) router.push(`/decisions/${res.decision.id}`);
  if (action.type === "open_project" && action.path) {
    // Opens the folder in VS Code via its URL handler (works when VS Code is installed locally).
    window.location.href = `vscode://file/${String(action.path).replace(/\\/g, "/")}`;
  }
  return res;
}
