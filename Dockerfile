# Sunnyside Beach - Production Cloud Image
FROM odoo:19.0

USER root

# Copy our custom visitor management and sync modules
COPY custom-addons/sunnyside_visitor_management /mnt/extra-addons/sunnyside_visitor_management
COPY custom-addons/sunnyside_sync /mnt/extra-addons/sunnyside_sync

# Set proper ownership for the odoo runtime user
RUN chown -R odoo:odoo /mnt/extra-addons

USER odoo
