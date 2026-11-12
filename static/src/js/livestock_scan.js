/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, useRef, useState } from "@odoo/owl";

export class LivestockScan extends Component {
    static template = "mdv_agriculture_suite.LivestockScan";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.inputRef = useRef("rfidInput");
        this.state = useState({ rfid: "", noMatch: false, searching: false });
        onMounted(() => this.inputRef.el.focus());
    }

    async onKeydown(event) {
        if (event.key !== "Enter") {
            return;
        }
        event.preventDefault();
        const rfid = this.state.rfid.trim();
        if (!rfid || this.state.searching) {
            return;
        }

        this.state.searching = true;
        try {
            const animals = await this.orm.searchRead(
                "mdv.agri.animal",
                [["rfid", "=", rfid]],
                ["id"],
                { limit: 2 }
            );
            if (animals.length === 1) {
                await this.action.doAction({
                    type: "ir.actions.act_window",
                    res_model: "mdv.agri.animal",
                    res_id: animals[0].id,
                    views: [[false, "form"]],
                });
            } else if (animals.length > 1) {
                await this.action.doAction({
                    type: "ir.actions.act_window",
                    name: "Animals",
                    res_model: "mdv.agri.animal",
                    domain: [["rfid", "=", rfid]],
                    views: [[false, "list"], [false, "form"]],
                });
            } else {
                this.state.noMatch = true;
            }
        } finally {
            this.state.searching = false;
        }
    }

    rescan() {
        this.state.rfid = "";
        this.state.noMatch = false;
        this.inputRef.el.focus();
    }

    createAnimal() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: "New Animal",
            res_model: "mdv.agri.animal",
            views: [[false, "form"]],
            context: { default_rfid: this.state.rfid.trim() },
        });
    }
}

registry.category("actions").add("mdv_agri_livestock_scan", LivestockScan);
