

set -uo pipefail

export LC_ALL=C

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${RAIZ}/bin"
SAIDA="${RAIZ}/resultados"
PORTA=9200

DURACAO="${1:-8}"
shift || true
CONEXOES=("${@:-1000 5000 10000}")
[ $# -eq 0 ] && CONEXOES=(1000 5000 10000)

mkdir -p "$SAIDA"
CSV="${SAIDA}/c10k.csv"

if [ "$(ulimit -Sn)" -lt 65536 ]; then
    ulimit -n 65536 2>/dev/null || {
        echo "erro: eleve o limite de descritores (ulimit -n 65536)" >&2
        exit 1
    }
fi

TICKS=$(getconf CLK_TCK)

cpu_segundos() {  # $1 = pid
    awk -v t="$TICKS" '{print ($14 + $15) / t}' "/proc/$1/stat" 2>/dev/null || echo 0
}
rss_kb() {
    awk '/^VmRSS:/ {print $2}' "/proc/$1/status" 2>/dev/null || echo 0
}
threads() {
    awk '/^Threads:/ {print $2}' "/proc/$1/status" 2>/dev/null || echo 0
}

echo "servidor,conexoes,aceitas,recusadas,rss_mb,cpu_s,threads,msgs,p50_us,p95_us,p99_us" > "$CSV"

for servidor in epoll select threads; do
    case "$servidor" in
        epoll)   CMD=("$BIN/servidor_epoll" "$PORTA" --eco) ;;
        select)  CMD=("$BIN/servidor_select" "$PORTA" --eco) ;;
        threads) CMD=("$BIN/servidor_threads" "$PORTA" --eco --pilha-kb 256) ;;
    esac

    for n in "${CONEXOES[@]}"; do
        ativas=$(( n / 100 ))
        [ "$ativas" -lt 1 ] && ativas=1

        LOG="${SAIDA}/.srv.$$"
        "${CMD[@]}" >/dev/null 2>"$LOG" &
        PID=$!
        sleep 0.5
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "$servidor,$n,0,$n,0,0,0,0,0,0,0" >> "$CSV"
            echo "  $servidor/$n: servidor nao subiu"
            continue
        fi

        cpu0=$(cpu_segundos "$PID")

        # RSS e contagem de threads precisam ser amostrados DURANTE a corrida:
        # ao final, as conexoes ja fecharam e as threads ja sairam.
        PICO="${SAIDA}/.pico.$$"
        : > "$PICO"
        ( while kill -0 "$PID" 2>/dev/null; do
              echo "$(rss_kb "$PID") $(threads "$PID")" >> "$PICO"
              sleep 0.2
          done ) &
        AMOSTRADOR=$!

        linha=$("$BIN/carga_conexoes" 127.0.0.1 "$PORTA" "$n" "$ativas" "$DURACAO" 2>/dev/null)

        cpu1=$(cpu_segundos "$PID")
        kill "$AMOSTRADOR" 2>/dev/null; wait "$AMOSTRADOR" 2>/dev/null
        rss=$(awk 'BEGIN{m=0} {if ($1+0 > m) m=$1+0} END{print m}' "$PICO")
        thr=$(awk 'BEGIN{m=0} {if ($2+0 > m) m=$2+0} END{print m}' "$PICO")
        rm -f "$PICO"

        kill -9 "$PID" 2>/dev/null
        wait "$PID" 2>/dev/null

        cpu=$(awk -v a="$cpu0" -v b="$cpu1" 'BEGIN{printf "%.2f", b-a}')
        rssmb=$(awk -v r="$rss" 'BEGIN{printf "%.1f", r/1024}')

        # `vivas` = conexoes que o servidor ainda mantinha ao fim da corrida.
        # E a metrica honesta: connect() sucede pelo backlog mesmo quando o
        # servidor recusa logo em seguida (caso do select com FD_SETSIZE).
        viv=$(sed -n 's/.*vivas=\([0-9]*\).*/\1/p' <<<"$linha")
        msg=$(sed -n 's/.*msgs=\([0-9]*\).*/\1/p' <<<"$linha")
        p50=$(sed -n 's/.*p50_us=\([0-9.]*\).*/\1/p' <<<"$linha")
        p95=$(sed -n 's/.*p95_us=\([0-9.]*\).*/\1/p' <<<"$linha")
        p99=$(sed -n 's/.*p99_us=\([0-9.]*\).*/\1/p' <<<"$linha")
        rec=$(( n - ${viv:-0} ))
        [ "$rec" -lt 0 ] && rec=0
        rm -f "$LOG"

        echo "$servidor,$n,${viv:-0},$rec,$rssmb,$cpu,$thr,${msg:-0},${p50:-0},${p95:-0},${p99:-0}" >> "$CSV"
        printf "  %-8s %6s conexoes | aceitas=%-6s recusadas=%-6s rss=%7s MB | cpu=%6ss | thr=%-6s | msgs=%-9s p95=%8s us\n" \
            "$servidor" "$n" "${viv:-0}" "$rec" "$rssmb" "$cpu" "$thr" "${msg:-0}" "${p95:-0}"

        # deixa o kernel reciclar sockets antes da proxima corrida
        sleep 2
    done
done

echo
echo "CSV em $CSV"
column -s, -t "$CSV"
