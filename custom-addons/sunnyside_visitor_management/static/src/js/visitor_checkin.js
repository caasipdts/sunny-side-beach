/* Sunnyside Beach - Progressive Visitor Check-in Client Helper */
(function () {
    'use strict';

    function initializeVisitorCheckin() {
        const form = document.querySelector("#visitorCheckinForm") || document.querySelector("#sunnyside_checkin_form");
        if (!form || form.dataset.initialized === '1') {
            return;
        }
        form.dataset.initialized = '1';

        const phone = form.querySelector("#phone");
        const name = form.querySelector("#name");
        const locationSelect = form.querySelector("#location_id");
        const email = form.querySelector("#email");
        const registrationFields = form.querySelector("#newRegistrationFields");
        const additionalDetails = form.querySelector("#additionalDetails");
        const lookupButton = form.querySelector("#lookupBtn") || form.querySelector("#btn_continue_phone");
        const changePhoneButton = form.querySelector("#changePhoneBtn") || form.querySelector("#btn_back_to_phone");
        const submitButton = form.querySelector("#submitBtn") || form.querySelector("#btn_submit_register");
        const phoneValidationMessage = form.querySelector("#phoneValidationMessage");
        const message = form.querySelector("#lookupMessage");
        const formAction = form.querySelector("#form_action");

        let checkedPhone = null;
        let isSubmitting = false;

        function resetLookup() {
            checkedPhone = null;
            if (phone) {
                phone.readOnly = false;
                phone.classList.remove("is-invalid");
                phone.removeAttribute("aria-invalid");
            }
            if (registrationFields) registrationFields.hidden = true;
            if (additionalDetails) additionalDetails.hidden = true;
            if (lookupButton) lookupButton.hidden = false;
            if (changePhoneButton) changePhoneButton.hidden = true;
            if (name) name.required = false;
            if (phoneValidationMessage) phoneValidationMessage.hidden = true;
            if (message) message.classList.add("d-none");
            if (formAction) formAction.value = "lookup";
        }

        if (phone) {
            phone.addEventListener("input", () => {
                if (checkedPhone !== null && phone.value.trim() !== checkedPhone) {
                    resetLookup();
                }
            });

            phone.addEventListener("keydown", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    lookupPhone();
                }
            });
        }

        if (changePhoneButton) {
            changePhoneButton.addEventListener("click", () => {
                resetLookup();
                if (phone) phone.focus();
            });
        }

        function validatePhone() {
            if (!phone) return false;
            const value = phone.value.trim();
            const digits = value.replace(/\D/g, "");
            const valid = /^\+?[\d\s()-]+$/.test(value) && digits.length >= 8 && digits.length <= 15;
            phone.classList.toggle("is-invalid", !valid);
            phone.toggleAttribute("aria-invalid", !valid);
            if (phoneValidationMessage) {
                phoneValidationMessage.hidden = valid;
            }
            return valid;
        }

        async function lookupPhone() {
            if (isSubmitting || (lookupButton && lookupButton.disabled)) {
                return;
            }

            if (!validatePhone()) {
                if (phone) phone.focus();
                return;
            }

            const phoneNumber = phone.value.trim();
            checkedPhone = null;
            isSubmitting = true;
            if (lookupButton) {
                lookupButton.disabled = true;
                lookupButton.dataset.origText = lookupButton.textContent;
                lookupButton.textContent = "Checking...";
            }
            if (message) {
                message.classList.add("d-none");
            }

            try {
                const formData = new FormData(form);
                formData.set("action", "lookup");
                formData.set("is_ajax", "1");
                formData.set("phone", phoneNumber);

                const response = await fetch("/sunnyside/check-in", {
                    method: "POST",
                    body: formData,
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json",
                    },
                });

                if (!response.ok) {
                    throw new Error(`HTTP Error ${response.status}`);
                }

                const result = await response.json();

                if (phone.value.trim() !== phoneNumber) {
                    return;
                }

                checkedPhone = phoneNumber;

                if (result.status === "existing") {
                    // Existing Visitor -> Check-in complete! Render Screenshot 3
                    renderInstantSuccess(result);
                    return;
                } else if (result.status === "new") {
                    // New Visitor -> Reveal fields as shown in Screenshot 2
                    phone.blur();
                    phone.readOnly = true;
                    if (lookupButton) lookupButton.hidden = true;
                    if (changePhoneButton) changePhoneButton.hidden = false;
                    if (registrationFields) registrationFields.hidden = false;
                    if (additionalDetails) additionalDetails.hidden = false;
                    if (name) {
                        name.required = true;
                        name.focus();
                    }
                    if (formAction) formAction.value = "register";

                    if (message) {
                        message.classList.remove("d-none", "alert-danger");
                        message.classList.add("alert-info");
                        message.innerHTML = '<div class="fw-bold">Happy to Have You Here!</div><div class="small">Just a few details and you\'re all set!</div>';
                    }
                } else {
                    if (message) {
                        message.classList.remove("d-none", "alert-info");
                        message.classList.add("alert-danger");
                        message.textContent = result.message || "Please check the phone number entered.";
                    }
                }
            } catch (error) {
                if (phone.value.trim() !== phoneNumber) {
                    return;
                }
                console.warn("Async phone lookup failed, falling back to form submit:", error);
                if (formAction) formAction.value = "lookup";
                form.submit();
            } finally {
                isSubmitting = false;
                if (lookupButton) {
                    lookupButton.disabled = false;
                    if (lookupButton.dataset.origText) {
                        lookupButton.textContent = lookupButton.dataset.origText;
                    }
                }
            }
        }

        if (lookupButton) {
            lookupButton.addEventListener("click", lookupPhone);
        }

        // Form submission for new visitor registration
        form.addEventListener("submit", async (event) => {
            if (event.submitter === lookupButton || (document.activeElement === phone && formAction.value !== "register")) {
                event.preventDefault();
                if (checkedPhone !== phone.value.trim()) {
                    lookupPhone();
                }
                return;
            }

            // Require phone check before final registration
            if (checkedPhone !== phone.value.trim()) {
                event.preventDefault();
                if (!validatePhone()) {
                    phone.focus();
                    return;
                }
                lookupButton.focus();
                if (message) {
                    message.classList.remove("d-none", "alert-info");
                    message.classList.add("alert-danger");
                    message.textContent = "Check your phone number before completing check-in.";
                }
                return;
            }

            // Validate Name
            const nameVal = (name?.value || "").trim();
            if (!nameVal || nameVal.length < 2) {
                event.preventDefault();
                showError("name_feedback", "Please enter your name.");
                if (name) name.focus();
                return;
            }

            // Validate Location
            const locationId = locationSelect?.value;
            if (!locationId) {
                event.preventDefault();
                showError("location_feedback", "Please select your area or location.");
                if (locationSelect) locationSelect.focus();
                return;
            }

            // Validate Email if provided
            const emailVal = (email?.value || "").trim();
            if (emailVal) {
                const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (!emailPattern.test(emailVal)) {
                    event.preventDefault();
                    showError("email_feedback", "Please enter a valid email address.");
                    if (email) email.focus();
                    return;
                }
            }

            // AJAX Submission
            event.preventDefault();
            if (isSubmitting) return;

            isSubmitting = true;
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.dataset.origText = submitButton.textContent;
                submitButton.textContent = "Submitting...";
            }

            try {
                const formData = new FormData(form);
                formData.set("action", "register");
                formData.set("is_ajax", "1");
                formData.set("privacy_acknowledged", "1");

                const response = await fetch("/sunnyside/check-in", {
                    method: "POST",
                    body: formData,
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json",
                    },
                });

                if (!response.ok) {
                    throw new Error(`HTTP Error ${response.status}`);
                }

                const data = await response.json();

                if (data.status === "success") {
                    renderInstantSuccess(data);
                } else if (data.status === "validation_error" && data.errors) {
                    for (const [field, msg] of Object.entries(data.errors)) {
                        showError(`${field}_feedback`, msg);
                    }
                } else {
                    if (message) {
                        message.classList.remove("d-none", "alert-info");
                        message.classList.add("alert-danger");
                        message.textContent = data.message || "An error occurred while processing registration.";
                    }
                }
            } catch (err) {
                console.warn("Async registration failed, submitting standard form:", err);
                form.submit();
            } finally {
                isSubmitting = false;
                if (submitButton) {
                    submitButton.disabled = false;
                    if (submitButton.dataset.origText) {
                        submitButton.textContent = submitButton.dataset.origText;
                    }
                }
            }
        });

        function showError(elementId, errorMsg) {
            const el = document.getElementById(elementId);
            if (el) {
                el.textContent = errorMsg;
                el.classList.remove("d-none");
            }
        }

        // Render Screenshot 3 Welcome / Success Card
        function renderInstantSuccess(data) {
            const wrap = document.querySelector("#wrap.visitor-checkin-page") || document.querySelector(".visitor-checkin-page") || document.querySelector(".visitor-checkin-shell");
            const visitorName = data.visitor_name || "Guest";
            const sourceVal = document.getElementById("source")?.value || "qr_code";

            if (wrap) {
                wrap.innerHTML = `
                    <main class="visitor-checkin-success-card">
                        <div class="text-center mb-3">
                            <img src="/sunnyside_visitor_management/static/src/img/sunnyside_logo.jpg" 
                                 class="visitor-checkin-logo" 
                                 alt="Sunny Side Logo"/>
                        </div>
                        <h1 class="visitor-checkin-title">You're Checked-In, ${visitorName}!</h1>
                        <p class="visitor-checkin-message">Enjoy your time with us! 🌴</p>
                        <a href="/sunnyside/check-in?source=${encodeURIComponent(sourceVal)}" class="btn fw-bold visitor-checkin-primary">Back to home</a>
                    </main>
                `;
            }
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initializeVisitorCheckin);
    } else {
        initializeVisitorCheckin();
    }
})();
