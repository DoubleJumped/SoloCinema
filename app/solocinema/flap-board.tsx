"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { BoardRow } from "./board-utils";

const CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/:&+- ";
const LOGO = "SOLOCINEMA";
const COLS = { time: 5, date: 6, film: 24, theatre: 13, seats: 6 } as const;
const FLIP_STEP_MS = 105;
const REFLIP_EVERY_MS = 17000;

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
        <span
          key={index}
          className={`tile${ch !== " " && color ? ` ${color}` : ""}`}
          data-ch={ch}
        >
          <b className="ch">{ch}</b>
        </span>
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
  const rowsKey = rows.map((row) => row.id).join("|");

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

    function flipTile(tile: HTMLElement, delay: number) {
      const ch = tile.querySelector<HTMLElement>(".ch");
      const final = tile.dataset.ch ?? " ";
      if (!ch || reducedMotion) {
        return;
      }
      later(() => {
        tile.classList.add("flipping");
        const steps = 3 + Math.floor(Math.random() * 4);
        for (let step = 0; step < steps; step++) {
          later(() => {
            ch.textContent = randChar();
          }, step * FLIP_STEP_MS);
        }
        later(() => {
          ch.textContent = final;
          tile.classList.remove("flipping");
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
    root
      .querySelectorAll<HTMLElement>(".brow")
      .forEach((row, index) => flipGroup(row, index * 70));

    let interval: number | undefined;
    if (!reducedMotion) {
      interval = window.setInterval(() => {
        if (Math.random() < 0.33) {
          flipLogo();
        }
        const rowEls = root.querySelectorAll<HTMLElement>(".brow");
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
      logo?.removeEventListener("click", flipLogo);
      logo?.removeEventListener("keydown", onLogoKey);
      root.querySelectorAll<HTMLElement>(".tile.flipping").forEach((tile) => {
        tile.classList.remove("flipping");
        const ch = tile.querySelector<HTMLElement>(".ch");
        if (ch) {
          ch.textContent = tile.dataset.ch ?? " ";
        }
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
              >
                <b className="ch">{ch}</b>
              </span>
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
          {rows.map((row) => (
            <a
              key={row.id}
              className="brow grid-cols"
              href={row.ticketUrl}
              target="_blank"
              rel="noreferrer"
              aria-label={row.aria}
            >
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
            </a>
          ))}
        </div>
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
