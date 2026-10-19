FROM quay.io/keycloak/keycloak:26.8.1 AS builder
ENV KC_DB=postgres KC_HEALTH_ENABLED=true
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.8.1
COPY --from=builder /opt/keycloak/ /opt/keycloak/
COPY --chmod=755 infrastructure/keycloak/entrypoint.sh /opt/dkman/entrypoint.sh
ENTRYPOINT ["/bin/bash", "/opt/dkman/entrypoint.sh"]
