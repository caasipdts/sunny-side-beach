/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

class SunnysideSyncStatus extends Component {
    static template = "sunnyside_sync.Status";

    setup() {
        this.status = useState({
            state: "unknown",
            pending_count: 0,
            quarantined_count: 0,
            last_success_at: false,
            offline_since: false,
            last_error: "",
        });
        this.timer = null;
        this.refresh = this.refresh.bind(this);
        onMounted(() => {
            this.refresh();
            this.timer = setInterval(this.refresh, 20000);
        });
        onWillUnmount(() => clearInterval(this.timer));
    }

    async refresh() {
        try {
            Object.assign(this.status, await rpc("/sunnyside_sync/status"));
        } catch {
            this.status.state = "unknown";
            this.status.last_error = "Sync status is unavailable.";
        }
    }

    get label() {
        const label = {
            online: "Online",
            degraded: "Degraded",
            offline: "Offline",
            unknown: "Sync",
        }[this.status.state] || "Sync";
        return `${label} · ${this.status.pending_count} pending`;
    }

    get title() {
        if (this.status.state === "offline") {
            return `Offline since ${this.status.offline_since || "unknown"}; ${this.status.pending_count} records queued. ${this.status.last_error}`;
        }
        return `${this.status.last_error || "Synchronization status"} · ${this.status.quarantined_count} quarantined`;
    }
}

registry.category("systray").add("sunnyside_sync.status", {
    Component: SunnysideSyncStatus,
}, { sequence: 80 });
