/** Farm dashboard: crops, scouting, weather alerts and livestock in one screen. */
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class AgriDashboard extends Component {
    static template = "mdv_agriculture_suite.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("mdv.agri.dashboard", "get_dashboard_data", []);
    }

    money(value) {
        const cur = this.state.data.currency;
        const amount = Math.round(value || 0).toLocaleString();
        return cur.position === "before" ? `${cur.symbol} ${amount}` : `${amount} ${cur.symbol}`;
    }

    pct(budget, actual) {
        return budget ? Math.min(100, Math.round((actual / budget) * 100)) : 0;
    }

    open(xmlid) {
        this.action.doAction(xmlid);
    }

    openRecord(model, id) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: model, res_id: id, views: [[false, "form"]] });
    }

    get kpis() {
        const k = this.state.data.kpi;
        return [
            { label: _t("Area under crop (ha)"), value: k.area_planted, action: "mdv_agriculture_suite.action_agri_crop_plan" },
            { label: _t("Active crop plans"), value: k.active_plans, action: "mdv_agriculture_suite.action_agri_crop_plan" },
            { label: _t("Season cost, budget %s", this.money(k.season_budget)), value: this.money(k.season_actual), action: "mdv_agriculture_suite.action_agri_cost_report" },
            { label: _t("Harvest lots this season"), value: k.season_harvest_lots, action: "mdv_agriculture_suite.action_agri_harvest" },
            { label: _t("Open scouting, %s high or critical", k.critical_scouting), value: k.open_scouting, action: "mdv_agriculture_suite.action_agri_scouting" },
            { label: _t("Animals and birds"), value: k.animals, action: "mdv_agriculture_suite.action_agri_herd" },
            { label: _t("Milk last 7 days (L)"), value: k.milk_7d, action: "mdv_agriculture_suite.action_agri_milk_log" },
            { label: _t("Eggs last 7 days"), value: k.eggs_7d, action: "mdv_agriculture_suite.action_agri_egg_log" },
            { label: _t("Vet treatments due"), value: k.vet_due, action: "mdv_agriculture_suite.action_agri_vet_treatment" },
            { label: _t("Crop requests to review"), value: k.requests, action: "mdv_agriculture_suite.action_agri_crop_request" },
        ];
    }
}

registry.category("actions").add("mdv_agri_dashboard", AgriDashboard);
