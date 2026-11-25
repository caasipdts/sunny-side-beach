/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { _t } from "@web/core/l10n/translation";

export class SeatingDashboard extends Component {
    static template = "sunnyside_visitor_management.SeatingDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            error: null,
            metrics: {
                total_units: 0,
                available_units: 0,
                reserved_units: 0,
                total_areas: 0,
            },
            areas: [],
            seatingTypes: [],
            units: [],
            currency: {
                symbol: '₦',
                position: 'before',
            },

            // Navigation and Filters
            selectedAreaId: null, // null for 'All'
            searchQuery: '',
            statusFilter: 'all', // 'all', 'available', 'reserved'
            typeFilter: 'all',

            // Workflow A/B Context
            contextVisitorId: null,
            contextVisitId: null,
            contextVisitorName: '',
            contextVisitName: '',

            // Modal dialogs
            activeModal: null, // 'booking' | 'details' | 'payment' | 'release' | null
            selectedUnit: null,
            selectedBooking: null,

            // Booking Form State
            bookingForm: {
                unitId: null,
                guestCount: 1,
                visitId: null,
                visitorSearch: '',
                selectedVisit: null,
                eligibleVisits: [],
                loadingVisits: false,
                recordPaymentNow: false,
                paymentAmount: 0.0,
                paymentMethod: 'cash',
                paymentReference: '',
                submitting: false,
                formError: '',
            },

            // Payment Form State
            paymentForm: {
                bookingId: null,
                amount: 0.0,
                paymentMethod: 'cash',
                paymentReference: '',
                submitting: false,
                formError: '',
            },

            // Release Form State
            releaseForm: {
                bookingId: null,
                unitName: '',
                amountDue: 0.0,
                submitting: false,
                formError: '',
            },
        });

        onWillStart(async () => {
            await this.initDashboard();
        });
    }

    async initDashboard() {
        // Read context parameters passed from Visitor or Visit form (Workflow A/B)
        const ctx = this.props.action.context || {};
        if (ctx.default_visitor_id) {
            this.state.contextVisitorId = parseInt(ctx.default_visitor_id);
        }
        if (ctx.default_visit_id) {
            this.state.contextVisitId = parseInt(ctx.default_visit_id);
        }

        // Fetch context visit/visitor names if supplied
        if (this.state.contextVisitId) {
            try {
                const visits = await this.orm.read("sunnyside.visit", [this.state.contextVisitId], ["name", "visitor_id"]);
                if (visits && visits.length) {
                    this.state.contextVisitName = visits[0].name;
                    if (visits[0].visitor_id) {
                        this.state.contextVisitorId = visits[0].visitor_id[0];
                        this.state.contextVisitorName = visits[0].visitor_id[1];
                    }
                }
            } catch (err) {
                console.warn("Could not read context visit:", err);
            }
        } else if (this.state.contextVisitorId) {
            try {
                const partners = await this.orm.read("res.partner", [this.state.contextVisitorId], ["name"]);
                if (partners && partners.length) {
                    this.state.contextVisitorName = partners[0].name;
                }
            } catch (err) {
                console.warn("Could not read context visitor:", err);
            }
        }

        await this.loadDashboardData();
    }

    async loadDashboardData() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call(
                "sunnyside.seating.unit",
                "get_dashboard_data",
                [],
                { area_id: this.state.selectedAreaId }
            );

            this.state.metrics = data.metrics || this.state.metrics;
            this.state.areas = data.areas || [];
            this.state.seatingTypes = data.seating_types || [];
            this.state.units = data.units || [];
            this.state.currency = data.currency || this.state.currency;
        } catch (err) {
            this.state.error = err.message || _t("Failed to load seating dashboard data.");
            console.error("Dashboard data load error:", err);
        } finally {
            this.state.loading = false;
        }
    }

    async refresh() {
        await this.loadDashboardData();
        this.notification.add(_t("Seating board refreshed with latest live availability."), {
            type: "info",
        });
    }

    // -------------------------------------------------------------------------
    // Filtering Logic
    // -------------------------------------------------------------------------
    get filteredUnits() {
        let result = this.state.units;

        // Area Filter
        if (this.state.selectedAreaId) {
            result = result.filter(u => u.area_id === this.state.selectedAreaId);
        }

        // Status Filter
        if (this.state.statusFilter === 'available') {
            result = result.filter(u => !u.is_reserved);
        } else if (this.state.statusFilter === 'reserved') {
            result = result.filter(u => u.is_reserved);
        }

        // Seating Type Filter
        if (this.state.typeFilter !== 'all') {
            result = result.filter(u => u.seating_type === this.state.typeFilter);
        }

        // Search Query
        if (this.state.searchQuery && this.state.searchQuery.trim()) {
            const q = this.state.searchQuery.trim().toLowerCase();
            result = result.filter(u => {
                const nameMatch = u.name && u.name.toLowerCase().includes(q);
                const areaMatch = u.area_name && u.area_name.toLowerCase().includes(q);
                const visitorMatch = u.booking && u.booking.visitor_name && u.booking.visitor_name.toLowerCase().includes(q);
                const refMatch = u.booking && u.booking.name && u.booking.name.toLowerCase().includes(q);
                return nameMatch || areaMatch || visitorMatch || refMatch;
            });
        }

        return result;
    }

    selectArea(areaId) {
        this.state.selectedAreaId = areaId;
    }

    clearContext() {
        this.state.contextVisitorId = null;
        this.state.contextVisitId = null;
        this.state.contextVisitorName = '';
        this.state.contextVisitName = '';
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------
    formatCurrency(amount) {
        const val = Number(amount || 0).toLocaleString('en-US', {
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        });
        if (this.state.currency.position === 'after') {
            return `${val} ${this.state.currency.symbol}`;
        }
        return `${this.state.currency.symbol}${val}`;
    }

    getSeatingTypeIcon(type) {
        switch (type) {
            case 'beachfront_seat':
                return 'fa-umbrella';
            case 'cabana':
                return 'fa-home';
            case 'table':
                return 'fa-cutlery';
            default:
                return 'fa-th-large';
        }
    }

    getEstimatedBookingPrice(unit, guestCount) {
        if (!unit) return 0;
        const count = Math.max(1, parseInt(guestCount || 1));
        if (unit.pricing_mode === 'fixed') {
            return unit.fixed_price || 250000;
        }
        return (unit.price_per_guest || 20000) * count;
    }

    // -------------------------------------------------------------------------
    // Booking Modal & Actions
    // -------------------------------------------------------------------------
    async openBookingModal(unit) {
        this.state.selectedUnit = unit;
        this.state.activeModal = 'booking';

        const defaultGuests = Math.max(1, unit.capacity_min || 1);
        const estPrice = this.getEstimatedBookingPrice(unit, defaultGuests);

        this.state.bookingForm = {
            unitId: unit.id,
            guestCount: defaultGuests,
            visitId: this.state.contextVisitId || null,
            visitorSearch: '',
            selectedVisit: null,
            eligibleVisits: [],
            loadingVisits: false,
            recordPaymentNow: false,
            paymentAmount: estPrice,
            paymentMethod: 'cash',
            paymentReference: '',
            submitting: false,
            formError: '',
        };

        await this.searchEligibleVisits();

        // If context visit was given, preselect it
        if (this.state.contextVisitId) {
            const match = this.state.bookingForm.eligibleVisits.find(v => v.id === this.state.contextVisitId);
            if (match) {
                this.state.bookingForm.selectedVisit = match;
            }
        }
    }

    async searchEligibleVisits() {
        this.state.bookingForm.loadingVisits = true;
        try {
            const visits = await this.orm.call(
                "sunnyside.seating.unit",
                "get_checked_in_visits",
                [],
                {
                    search_query: this.state.bookingForm.visitorSearch,
                    visitor_id: this.state.contextVisitorId || undefined,
                }
            );
            this.state.bookingForm.eligibleVisits = visits;
            if (visits.length === 1 && !this.state.bookingForm.selectedVisit) {
                this.state.bookingForm.selectedVisit = visits[0];
                this.state.bookingForm.visitId = visits[0].id;
            }
        } catch (err) {
            console.error("Error searching eligible visits:", err);
        } finally {
            this.state.bookingForm.loadingVisits = false;
        }
    }

    onSelectVisit(visit) {
        this.state.bookingForm.selectedVisit = visit;
        this.state.bookingForm.visitId = visit.id;
        this.state.bookingForm.formError = '';
    }

    onGuestCountChange(newCount) {
        const count = Math.max(1, parseInt(newCount || 1));
        this.state.bookingForm.guestCount = count;
        const estPrice = this.getEstimatedBookingPrice(this.state.selectedUnit, count);
        if (this.state.bookingForm.recordPaymentNow) {
            this.state.bookingForm.paymentAmount = estPrice;
        }
    }

    onToggleRecordPayment(checked) {
        this.state.bookingForm.recordPaymentNow = checked;
        if (checked) {
            this.state.bookingForm.paymentAmount = this.getEstimatedBookingPrice(
                this.state.selectedUnit,
                this.state.bookingForm.guestCount
            );
        } else {
            this.state.bookingForm.paymentAmount = 0.0;
        }
    }

    async submitBooking() {
        const form = this.state.bookingForm;
        const unit = this.state.selectedUnit;

        form.formError = '';

        if (!form.visitId) {
            form.formError = _t("Please select an eligible checked-in visit.");
            return;
        }

        // Validate guest count client-side before call
        if (form.guestCount < unit.capacity_min) {
            form.formError = _t(`Guest count must be at least ${unit.capacity_min}.`);
            return;
        }
        if (unit.capacity_max && form.guestCount > unit.capacity_max) {
            form.formError = _t(`Guest count cannot exceed maximum capacity of ${unit.capacity_max}.`);
            return;
        }
        const estPrice = this.getEstimatedBookingPrice(unit, form.guestCount);
        if (form.recordPaymentNow && form.paymentAmount > estPrice) {
            form.formError = _t(`Payment amount cannot exceed booking total of ${this.formatCurrency(estPrice)}.`);
            return;
        }

        form.submitting = true;
        try {
            const res = await this.orm.call(
                "sunnyside.seating.unit",
                "create_dashboard_booking",
                [],
                {
                    visit_id: form.visitId,
                    unit_id: unit.id,
                    guest_count: form.guestCount,
                    payment_amount: form.recordPaymentNow ? form.paymentAmount : 0.0,
                    payment_method: form.paymentMethod,
                    payment_reference: form.paymentReference,
                }
            );

            this.notification.add(
                _t(`Reservation ${res.booking_name} confirmed for ${unit.name}!`),
                { type: "success" }
            );

            this.closeModal();
            await this.loadDashboardData();
        } catch (err) {
            form.formError = err.data && err.data.message ? err.data.message : err.message || _t("Failed to create reservation.");
        } finally {
            form.submitting = false;
        }
    }

    // -------------------------------------------------------------------------
    // Details Modal
    // -------------------------------------------------------------------------
    openDetailsModal(unit) {
        if (!unit.is_reserved || !unit.booking) {
            return;
        }
        this.state.selectedUnit = unit;
        this.state.selectedBooking = unit.booking;
        this.state.activeModal = 'details';
    }

    // -------------------------------------------------------------------------
    // Payment Modal
    // -------------------------------------------------------------------------
    openPaymentModal(booking) {
        const b = booking || this.state.selectedBooking;
        if (!b) return;

        this.state.selectedBooking = b;
        this.state.activeModal = 'payment';
        this.state.paymentForm = {
            bookingId: b.id,
            amount: b.amount_due || 0.0,
            paymentMethod: 'cash',
            paymentReference: '',
            submitting: false,
            formError: '',
        };
    }

    setQuickPayment(amount) {
        this.state.paymentForm.amount = amount;
    }

    async submitPayment() {
        const form = this.state.paymentForm;
        const booking = this.state.selectedBooking;
        form.formError = '';

        const amount = parseFloat(form.amount || 0);
        if (amount <= 0) {
            form.formError = _t("Payment amount must be greater than zero.");
            return;
        }
        if (amount > booking.amount_due) {
            form.formError = _t(`Payment amount cannot exceed outstanding balance of ${this.formatCurrency(booking.amount_due)}.`);
            return;
        }

        form.submitting = true;
        try {
            await this.orm.call(
                "sunnyside.seating.unit",
                "record_dashboard_payment",
                [],
                {
                    booking_id: form.bookingId,
                    amount: amount,
                    payment_method: form.paymentMethod,
                    reference: form.paymentReference,
                }
            );

            this.notification.add(
                _t(`Payment of ${this.formatCurrency(amount)} recorded successfully.`),
                { type: "success" }
            );

            this.closeModal();
            await this.loadDashboardData();
        } catch (err) {
            form.formError = err.data && err.data.message ? err.data.message : err.message || _t("Payment failed.");
        } finally {
            form.submitting = false;
        }
    }

    // -------------------------------------------------------------------------
    // Manual Release Modal
    // -------------------------------------------------------------------------
    openReleaseModal(booking, unit) {
        const b = booking || this.state.selectedBooking;
        const u = unit || this.state.selectedUnit;
        if (!b) return;

        this.state.selectedBooking = b;
        this.state.selectedUnit = u;
        this.state.activeModal = 'release';
        this.state.releaseForm = {
            bookingId: b.id,
            unitName: u ? u.name : '',
            amountDue: b.amount_due || 0,
            submitting: false,
            formError: '',
        };
    }

    async submitRelease() {
        const form = this.state.releaseForm;
        form.formError = '';
        form.submitting = true;

        try {
            await this.orm.call(
                "sunnyside.seating.unit",
                "release_dashboard_booking",
                [],
                {
                    booking_id: form.bookingId,
                }
            );

            this.notification.add(
                _t(`Reservation released. ${form.unitName} is now available.`),
                { type: "success" }
            );

            this.closeModal();
            await this.loadDashboardData();
        } catch (err) {
            form.formError = err.data && err.data.message ? err.data.message : err.message || _t("Release failed.");
        } finally {
            form.submitting = false;
        }
    }

    closeModal() {
        this.state.activeModal = null;
        this.state.selectedUnit = null;
        this.state.selectedBooking = null;
    }

    // -------------------------------------------------------------------------
    // Navigation to Backend Form Views
    // -------------------------------------------------------------------------
    openVisitorRecord(visitorId) {
        if (!visitorId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: visitorId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openVisitRecord(visitId) {
        if (!visitId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sunnyside.visit",
            res_id: visitId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openBookingRecord(bookingId) {
        if (!bookingId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sunnyside.booking",
            res_id: bookingId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("sunnyside_seating_dashboard", SeatingDashboard);

