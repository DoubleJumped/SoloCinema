"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { isSafeTicketUrl, type BoardRow } from "./board-utils";

const CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/:&+- ";
const LOGO = "SOLOCINEMA";
// seats needs 7 tiles for a full house at the 154-seat IMAX ("154/154")
const COLS = { time: 5, date: 6, film: 24, theatre: 13, seats: 7 } as const;
const FLIP_STEP_MS = 105;
const REFLIP_EVERY_MS = 17000;
// Server-render only the first screenful of rows; the rest stream in as the
// viewer scrolls so a big board doesn't ship megabytes of tile markup.
const INITIAL_ROWS = 40;
const ROW_CHUNK = 40;

type FlapBoardProps = {
  rows: BoardRow[];
  updatedLabel: string;
  counts: { empty: number; under: number; total: number };
  children?: ReactNode;
};

function Cell({
  text,
  count,
  color,
  extra
}: {
  text: string;
  count: number;
  color?: string;
  extra: string;
}) {
  const padded = text.toUpperCase().slice(0, count).padEnd(count, " ");
  return (
    <div className={`cell ${extra}`}>
      {Array.from(padded).map((ch, index) => (
        // the character itself renders via CSS `content: attr(data-ch)` so
        // each tile costs one element instead of two
        <span
          key={index}
          className={`tile${ch !== " " && color ? ` ${color}` : ""}`}
          data-ch={ch}
        />
      ))}
    </div>
  );
}

function Clock() {
  const [time, setTime] = useState("--:--:--");
  useEffect(() => {
    function tick() {
      const now = new Date();
      const pad = (value: number) => String(value).padStart(2, "0");
      setTime(
        `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
      );
    }
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <div className="clock" aria-hidden="true">
      {time}
    </div>
  );
}

export function FlapBoard({ rows, updatedLabel, counts, children }: FlapBoardProps) {
  const router = useRouter();
  const rootRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const rowsKey = rows.map((row) => row.id).join("|");
  const [visibleCount, setVisibleCount] = useState(INITIAL_ROWS);
  const shownRows = rows.slice(0, visibleCount);

  // start over from the first screenful whenever the filters change the rows
  useEffect(() => {
    setVisibleCount(INITIAL_ROWS);
  }, [rowsKey]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) {
      return;
    }
    if (!("IntersectionObserver" in window)) {
      setVisibleCount(rows.length);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisibleCount((count) => Math.min(count + ROW_CHUNK, rows.length));
        }
      },
      { rootMargin: "600px 0px" }
    );
    io.observe(sentinel);
    return () => io.disconnect();
  }, [rowsKey, visibleCount, rows.length]);

  // clicking the sign flips it (wired inside the effect) and also returns
  // the board to the default under-5 view
  function resetToDefaultView() {
    router.replace("/solocinema", { scroll: false });
  }

  useEffect(() => {
    const root = rootRef.current;
    if (!root) {
      return;
    }
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    const timers = new Set<number>();

    function later(fn: () => void, ms: number) {
      const id = window.setTimeout(() => {
        timers.delete(id);
        fn();
      }, ms);
      timers.add(id);
    }

    function randChar() {
      return CHARSET.charAt(Math.floor(Math.random() * CHARSET.length));
    }

    // While flipping, the tile shows `data-flip` instead of `data-ch` (see
    // .tile.flipping::after); removing the class reveals the real character.
    function flipTile(tile: HTMLElement, delay: number) {
      if (reducedMotion) {
        return;
      }
      later(() => {
        tile.setAttribute("data-flip", randChar());
        tile.classList.add("flipping");
        const steps = 3 + Math.floor(Math.random() * 4);
        for (let step = 1; step < steps; step++) {
          later(() => {
            tile.setAttribute("data-flip", randChar());
          }, step * FLIP_STEP_MS);
        }
        later(() => {
          tile.classList.remove("flipping");
          tile.removeAttribute("data-flip");
        }, (steps + 1) * FLIP_STEP_MS);
      }, delay);
    }

    function flipGroup(el: Element, base: number) {
      el.querySelectorAll<HTMLElement>(".tile").forEach((tile, index) => {
        flipTile(tile, base + index * 6 + Math.random() * 110);
      });
    }

    const logo = root.querySelector<HTMLElement>(".logo");
    const flipLogo = () => {
      if (logo) {
        flipGroup(logo, 0);
      }
    };
    const onLogoKey = (event: KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        flipLogo();
      }
    };
    logo?.addEventListener("click", flipLogo);
    logo?.addEventListener("keydown", onLogoKey);

    flipLogo();

    // The board can hold hundreds of rows. Flipping them all on mount queues
    // tens of thousands of timers and freezes the main thread, so only animate
    // rows as they scroll into view — each one flips once — and keep the
    // periodic reflip limited to rows the viewer can actually see.
    const visibleRows = new Set<HTMLElement>();
    const flippedRows = new WeakSet<HTMLElement>();
    let observer: IntersectionObserver | undefined;
    let rowWatcher: MutationObserver | undefined;

    if (!reducedMotion && "IntersectionObserver" in window) {
      observer = new IntersectionObserver(
        (entries) => {
          let entered = 0;
          for (const entry of entries) {
            const row = entry.target as HTMLElement;
            if (entry.isIntersecting) {
              visibleRows.add(row);
              if (!flippedRows.has(row)) {
                flippedRows.add(row);
                // stagger rows that appear together for the cascade effect
                flipGroup(row, entered++ * 70);
              }
            } else {
              visibleRows.delete(row);
            }
          }
        },
        { rootMargin: "120px 0px" }
      );
      root
        .querySelectorAll<HTMLElement>(".brow")
        .forEach((row) => observer!.observe(row));

      // rows mount lazily as the viewer scrolls — watch for them so they get
      // the same flip-into-view treatment without re-running this effect
      const rowsHost = root.querySelector(".rows");
      if (rowsHost) {
        rowWatcher = new MutationObserver((mutations) => {
          for (const mutation of mutations) {
            mutation.addedNodes.forEach((node) => {
              if (node instanceof HTMLElement && node.classList.contains("brow")) {
                observer!.observe(node);
              }
            });
          }
        });
        rowWatcher.observe(rowsHost, { childList: true });
      }
    }

    let interval: number | undefined;
    if (!reducedMotion) {
      interval = window.setInterval(() => {
        if (Math.random() < 0.33) {
          flipLogo();
        }
        const rowEls = [...visibleRows];
        if (rowEls.length) {
          flipGroup(rowEls[Math.floor(Math.random() * rowEls.length)], 0);
        }
      }, REFLIP_EVERY_MS);
    }

    return () => {
      timers.forEach((id) => window.clearTimeout(id));
      if (interval !== undefined) {
        window.clearInterval(interval);
      }
      observer?.disconnect();
      rowWatcher?.disconnect();
      logo?.removeEventListener("click", flipLogo);
      logo?.removeEventListener("keydown", onLogoKey);
      root.querySelectorAll<HTMLElement>(".tile.flipping").forEach((tile) => {
        tile.classList.remove("flipping");
        tile.removeAttribute("data-flip");
      });
    };
  }, [rowsKey]);

  return (
    <div ref={rootRef}>
      <header className="signage">
        <div className="brand">
          <h1
            className="logo"
            tabIndex={0}
            role="button"
            aria-label="SoloCinema — reset filters"
            title="Reset filters"
            onClick={resetToDefaultView}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                resetToDefaultView();
              }
            }}
          >
            {Array.from(LOGO).map((ch, index) => (
              <span
                key={index}
                className={`tile tile-logo${index >= 4 ? " c-amber" : ""}`}
                data-ch={ch}
                aria-hidden="true"
              />
            ))}
          </h1>
        </div>
        <div className="board-right">
          <div className="destino">
            REGINA <span>/</span> ALL THEATRES
          </div>
          <Clock />
          <div className="updated">
            <span className="pulse"></span> {updatedLabel}
          </div>
        </div>
      </header>

      {children}

      <section className="board" aria-label="Screenings board">
        <div className="board-head grid-cols" aria-hidden="true">
          <div className="hlabel">Time</div>
          <div className="hlabel">Date</div>
          <div className="hlabel">Film</div>
          <div className="hlabel">Theatre</div>
          <div className="hlabel">Seats Taken</div>
        </div>
        <div className="rows">
          {shownRows.map((row) => {
            const cells = (
              <>
                <Cell text={row.time} count={COLS.time} color="c-amber" extra="cell--time" />
                <Cell text={row.date} count={COLS.date} color="c-muted" extra="cell--date" />
                <Cell text={row.film} count={COLS.film} extra="cell--film" />
                <Cell text={row.theatre} count={COLS.theatre} extra="cell--theatre" />
                <Cell
                  text={row.seats}
                  count={COLS.seats}
                  color={`c-${row.tier}`}
                  extra="cell--seats"
                />
                <div className="card-plain">
                  <b>{row.theatre}</b> &nbsp;·&nbsp; {row.date}
                </div>
              </>
            );
            // Only link out when the ticket URL is a real http(s) URL; anything
            // else (a scraped javascript:/data: value, or empty) renders inert.
            return isSafeTicketUrl(row.ticketUrl) ? (
              <a
                key={row.id}
                className="brow grid-cols"
                href={row.ticketUrl}
                target="_blank"
                rel="noreferrer"
                aria-label={row.aria}
              >
                {cells}
              </a>
            ) : (
              <div key={row.id} className="brow grid-cols" aria-label={row.aria}>
                {cells}
              </div>
            );
          })}
        </div>
        {visibleCount < rows.length ? (
          <div ref={sentinelRef} className="rows-sentinel" aria-hidden="true" />
        ) : null}
        {rows.length === 0 ? (
          <div className="board-empty">
            No screenings match — try another date or turn{" "}
            <b>Under 5 Seats Sold</b> off
          </div>
        ) : null}
      </section>

      <div className="info">
        <div className="note">
          <span className="ldot g"></span> under 5 &nbsp;{" "}
          <span className="ldot a"></span> 5–19 &nbsp;{" "}
          <span className="ldot r"></span> 20+ &nbsp;{" "}
          <span className="ldot"></span> no data &nbsp;·&nbsp; seats taken is
          inferred from public seat maps
        </div>
        <div className="counts">
          <span className="g">{counts.empty} Empty</span> ·{" "}
          <span className="g">{counts.under} Under 5</span> ·{" "}
          <span className="a">{counts.total} Showings</span>
        </div>
      </div>
    </div>
  );
}
