FROM golang:1.21 AS builder
WORKDIR /app
COPY . .
RUN go build -o server .

FROM gcr.io/distroless/base
COPY --from=builder /app/server /server
EXPOSE 8080
CMD ["/server"]
