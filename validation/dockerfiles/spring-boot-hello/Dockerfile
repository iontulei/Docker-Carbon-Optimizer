# Un-optimized: DCO002 (consecutive RUNs) + DCO004 (no .dockerignore)
#             + DCO005 (single-stage maven) + DCO006 (unpinned maven tag)
FROM maven

WORKDIR /tmp/

COPY pom.xml /tmp/
COPY src /tmp/src/

RUN mvn dependency:resolve
RUN mvn package

EXPOSE 8080

CMD ["java", "-jar", "/tmp/target/hello-world-0.1.0.jar"]
