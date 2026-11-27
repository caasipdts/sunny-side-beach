FROM odoo:19.0
USER root
COPY ./custom-addons /mnt/extra-addons
RUN chown -R odoo:odoo /mnt/extra-addons && chmod -R a+rX /mnt/extra-addons
USER odoo
