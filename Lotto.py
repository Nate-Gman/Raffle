#!/usr/bin/env python3
"""
Raffle Monolith v11.0 - Generation 11 Full Multi-Tier Global System
====================================================================
Flask web dashboard edition: runs the simulation then serves a
casino-themed browser dashboard at http://localhost:5000
"""

import argparse
import csv
import hashlib
import hmac
import json
import multiprocessing as mp
import os
import secrets
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Tuple

from flask import Flask, jsonify, render_template_string, request


# ====================== GAME DEFINITIONS (All 5 tiers - 100% fair) ======================
@dataclass
class Game:
    name: str
    price: float
    winners_per_drawing: int
    monthly_payout: float
    payout_months: int
    description: str

GAMES = [
    Game("0.25",  0.25,    5, 8333.33,  6, "5 winners @ $8,333/mo for 6 months ($50k each) — Pool $250,000"),
    Game("4",      4.0,   80, 8333.33,  6, "80 winners @ $8,333/mo for 6 months ($50k each) — Pool $4,000,000"),
    Game("10",    10.0,   25,33333.33, 12, "25 winners @ $33,333/mo for 12 months ($400k each) — Pool $10,000,000"),
    Game("100",  100.0,  200,83333.33, 12, "200 winners @ $83,333/mo for 12 months ($1M each) — Pool $100,000,000"),
    Game("1000",1000.0, 2000,20833.33, 24, "2000 winners @ $20,833/mo for 24 months ($500k each) — Pool $1,000,000,000"),
]

TAX_RATE = 0.25
HAPPINESS_BOOST_PER_RECIPIENT = 0.45
DEFAULT_FINAL_PLAYERS = 4_000_000_000
DEFAULT_MONTHS = 32
DEFAULT_INITIAL_PLAYERS = 100_000_000
DEFAULT_BASE_INTENSITY = 20.0
DEFAULT_DAYS_PER_MONTH = 30.4375
REINVESTMENT_RATE = 0.95


# ====================== TICKET MANAGEMENT SYSTEM ======================
# Anti-fraud sequential ticketing: 1 – 1,000,000 per game per drawing.
# Every ticket has an HMAC signature to prevent forgery.

TICKETS_PER_DRAWING = 1_000_000
TICKET_SECRET_KEY = os.environ.get("TICKET_HMAC_KEY", secrets.token_hex(32))


@dataclass
class Ticket:
    """Immutable ticket record."""
    ticket_id: int          # Sequential 1–1,000,000
    game_id: str            # e.g. "0.25", "4", "10", "100", "1000"
    drawing_id: int         # Which drawing cycle (increments at 1M)
    owner_id: str           # Unique player identifier
    purchased_at: float     # Unix timestamp
    signature: str          # HMAC-SHA256 for anti-fraud
    is_gift: bool = False
    gift_recipient: str = ""


class TicketRegistry:
    """
    Thread-safe sequential ticket issuer for all game tiers.
    Each game+drawing pair issues tickets numbered 1..1,000,000.
    When a drawing fills, it auto-fires and increments the drawing ID.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Per-game state: {game_id: {drawing_id, next_ticket, tickets[], ledger[]}}
        self._games: Dict[str, Dict] = {}
        for g in GAMES:
            self._games[g.name] = {
                "drawing_id": 1,
                "next_ticket": 1,
                "tickets": [],          # Current drawing's tickets
                "past_drawings": [],    # List of completed drawing results
                "ledger": [],           # Transaction log
                "total_revenue": 0.0,
            }

    def _sign_ticket(self, game_id: str, drawing_id: int, ticket_id: int, owner_id: str) -> str:
        """Generate HMAC-SHA256 signature for anti-fraud verification."""
        msg = f"{game_id}:{drawing_id}:{ticket_id}:{owner_id}"
        return hmac.HMAC(
            TICKET_SECRET_KEY.encode(),
            msg.encode(),
            hashlib.sha256
        ).hexdigest()[:16]

    def verify_ticket(self, ticket: Ticket) -> bool:
        """Verify a ticket's HMAC signature is authentic."""
        expected = self._sign_ticket(
            ticket.game_id, ticket.drawing_id, ticket.ticket_id, ticket.owner_id
        )
        return hmac.compare_digest(ticket.signature, expected)

    def purchase_tickets(self, game_id: str, owner_id: str, qty: int,
                         gift_to: str = "") -> Dict:
        """
        Issue sequential tickets. Returns dict with ticket details.
        Max 10 per purchase. Raises ValueError on invalid input.
        """
        if qty < 1 or qty > 10:
            raise ValueError("Must buy 1-10 tickets per transaction")
        if game_id not in self._games:
            raise ValueError(f"Invalid game: {game_id}")

        game = next(g for g in GAMES if g.name == game_id)
        total_cost = qty * game.price

        with self._lock:
            gs = self._games[game_id]
            issued = []

            for _ in range(qty):
                tid = gs["next_ticket"]
                if tid > TICKETS_PER_DRAWING:
                    # Drawing is full — fire it
                    self._fire_drawing(game_id)
                    tid = gs["next_ticket"]

                sig = self._sign_ticket(game_id, gs["drawing_id"], tid, owner_id)
                ticket = Ticket(
                    ticket_id=tid,
                    game_id=game_id,
                    drawing_id=gs["drawing_id"],
                    owner_id=owner_id,
                    purchased_at=time.time(),
                    signature=sig,
                    is_gift=bool(gift_to),
                    gift_recipient=gift_to
                )
                gs["tickets"].append(ticket)
                gs["next_ticket"] += 1
                issued.append(ticket)

            # Record in ledger
            gs["ledger"].append({
                "type": "purchase",
                "owner": owner_id,
                "qty": qty,
                "cost": total_cost,
                "tickets": [t.ticket_id for t in issued],
                "drawing_id": gs["drawing_id"],
                "timestamp": time.time(),
                "gift_to": gift_to,
            })
            gs["total_revenue"] += total_cost

        return {
            "success": True,
            "tickets": [{
                "number": t.ticket_id,
                "formatted": f"{t.ticket_id:07d}",
                "signature": t.signature,
                "drawing_id": t.drawing_id,
                "game": game_id,
            } for t in issued],
            "cost": total_cost,
            "drawing_id": gs["drawing_id"],
            "tickets_remaining": TICKETS_PER_DRAWING - gs["next_ticket"] + 1,
            "percent_sold": ((gs["next_ticket"] - 1) / TICKETS_PER_DRAWING) * 100,
        }

    def _fire_drawing(self, game_id: str):
        """Execute a drawing: select winners randomly from issued tickets."""
        gs = self._games[game_id]
        game = next(g for g in GAMES if g.name == game_id)
        n_winners = min(game.winners_per_drawing, len(gs["tickets"]))

        # Cryptographically random winner selection
        import random
        rng = random.SystemRandom()
        winners = rng.sample(gs["tickets"], n_winners) if gs["tickets"] else []

        result = {
            "drawing_id": gs["drawing_id"],
            "game_id": game_id,
            "total_tickets": len(gs["tickets"]),
            "winners": [{
                "ticket_id": w.ticket_id,
                "owner_id": w.owner_id,
                "monthly_payout": game.monthly_payout,
                "duration_months": game.payout_months,
                "total_payout": game.monthly_payout * game.payout_months,
            } for w in winners],
            "fired_at": time.time(),
        }
        gs["past_drawings"].append(result)

        # Reset for next drawing
        gs["drawing_id"] += 1
        gs["next_ticket"] = 1
        gs["tickets"] = []
        return result

    def get_game_status(self, game_id: str) -> Dict:
        """Get current state of a game's ticket pool."""
        gs = self._games[game_id]
        return {
            "game_id": game_id,
            "drawing_id": gs["drawing_id"],
            "tickets_sold": gs["next_ticket"] - 1,
            "tickets_remaining": TICKETS_PER_DRAWING - gs["next_ticket"] + 1,
            "percent_sold": ((gs["next_ticket"] - 1) / TICKETS_PER_DRAWING) * 100,
            "total_revenue": gs["total_revenue"],
            "past_drawings": len(gs["past_drawings"]),
        }

    def get_all_status(self) -> Dict:
        """Get status for all games."""
        return {g: self.get_game_status(g) for g in self._games}

    def get_recent_winners(self, game_id: str, limit: int = 5) -> List[Dict]:
        """Get recent winners for a game."""
        gs = self._games[game_id]
        winners = []
        for drawing in reversed(gs["past_drawings"][-limit:]):
            for w in drawing["winners"][:3]:  # Top 3 from each drawing
                winners.append(w)
        return winners[:limit]


# Global ticket registry instance
ticket_registry = TicketRegistry()


class RaffleRegion:
    """One parallel world-region agent (multiprocessing)."""
    def __init__(self, region_id: int, player_share: float, intensity_factor: float = 1.0):
        self.region_id = region_id
        self.player_share = player_share
        self.intensity_factor = intensity_factor

    def simulate_month(self, month: int, total_players: int, base_intensity: float,
                       active_reinvestment_income: float) -> Dict:
        """Simulate one month for this region across ALL tiers."""
        players = int(total_players * self.player_share)

        base_spending = players * base_intensity * self.intensity_factor
        reinvest_spending = active_reinvestment_income * self.player_share * REINVESTMENT_RATE
        total_spending_power = base_spending + reinvest_spending

        results = {}
        for game in GAMES:
            if game.price == 0.25:
                allocation = 0.65
            elif game.price == 4.0:
                allocation = 0.15
            elif game.price == 10.0:
                allocation = 0.10
            elif game.price == 100.0:
                allocation = 0.06
            else:
                allocation = 0.04

            tier_spending = total_spending_power * allocation
            tickets = tier_spending / game.price
            drawings = tickets // 1_000_000
            new_winners = int(drawings * game.winners_per_drawing)

            results[game.name] = {
                "tickets_sold": int(tickets),
                "drawings": int(drawings),
                "new_winners": new_winners,
                "revenue": round(tickets * game.price, 2)
            }

        return {
            "region_id": self.region_id,
            "games": results,
            "total_spending_power": round(total_spending_power, 2)
        }


def run_region_simulation(args: Tuple) -> Dict:
    """Multiprocessing worker (stateless)."""
    region, month, total_players, base_intensity, active_income = args
    return region.simulate_month(month, total_players, base_intensity, active_income)


class GlobalRaffleSimulator:
    """Main monolithic engine - supports full ladder + all tiers."""

    def __init__(self, months: int = DEFAULT_MONTHS,
                 final_players: int = DEFAULT_FINAL_PLAYERS,
                 base_intensity: float = DEFAULT_BASE_INTENSITY):
        self.months = months
        self.final_players = final_players
        self.initial_players = DEFAULT_INITIAL_PLAYERS
        self.base_intensity = base_intensity

        self.regions = [
            RaffleRegion(0, 0.28, 1.08),
            RaffleRegion(1, 0.27, 0.95),
            RaffleRegion(2, 0.25, 1.15),
            RaffleRegion(3, 0.20, 0.98),
        ]

        self.active_cohorts = {game.name: deque(maxlen=game.payout_months) for game in GAMES}

    def _players_at_month(self, month: int) -> int:
        """Linear ramp-up to 4 billion players."""
        progress = min(month / self.months, 1.0)
        return int(self.initial_players + (self.final_players - self.initial_players) * progress)

    def run(self) -> List[Dict]:
        """Run the full simulation using parallel agents."""
        print(f"🚀 Starting Generation 11 Full-Tier Global Raffle Simulation")
        print(f"   → {self.final_players:,} players | {self.months} months | All 5 tiers + ladder\n")

        results: List[Dict] = []
        total_revenue_all_time = 0.0
        total_payouts_all_time = 0.0

        for month in range(1, self.months + 1):
            players = self._players_at_month(month)

            active_reinvestment_income = 0.0
            for game in GAMES:
                for start_month, winners in self.active_cohorts[game.name]:
                    if month - start_month < game.payout_months:
                        active_reinvestment_income += winners * game.monthly_payout

            pool_args = [(r, month, players, self.base_intensity, active_reinvestment_income)
                         for r in self.regions]
            with mp.Pool(processes=len(self.regions)) as pool:
                region_results = pool.map(run_region_simulation, pool_args)

            month_data = {"month": month, "players": players, "daily_intensity": self.base_intensity}
            monthly_revenue = 0.0
            active_recipients_total = 0

            for game in GAMES:
                new_winners = 0
                tickets_sold = 0
                game_revenue = 0.0

                for r in region_results:
                    g = r["games"][game.name]
                    new_winners += g["new_winners"]
                    tickets_sold += g["tickets_sold"]
                    game_revenue += g["revenue"]

                if new_winners > 0:
                    self.active_cohorts[game.name].append((month, new_winners))

                active_this_game = sum(w for _, w in self.active_cohorts[game.name])
                active_recipients_total += active_this_game
                monthly_revenue += game_revenue

                month_data.update({
                    f"{game.name}_new_winners": new_winners,
                    f"{game.name}_active_recipients": active_this_game,
                    f"{game.name}_tickets": tickets_sold,
                    f"{game.name}_revenue": round(game_revenue, 2),
                })

            monthly_payouts = 0.0
            for game in GAMES:
                for start_month, winners in self.active_cohorts[game.name]:
                    if month - start_month < game.payout_months:
                        monthly_payouts += winners * game.monthly_payout

            taxes_collected = monthly_payouts * TAX_RATE
            net_to_winners = monthly_payouts - taxes_collected

            total_revenue_all_time += monthly_revenue
            total_payouts_all_time += monthly_payouts

            month_data.update({
                "monthly_revenue": round(monthly_revenue, 2),
                "monthly_payouts": round(monthly_payouts, 2),
                "taxes_collected": round(taxes_collected, 2),
                "net_to_winners": round(net_to_winners, 2),
                "active_recipients_total": active_recipients_total,
                "happiness_impact": round(active_recipients_total * HAPPINESS_BOOST_PER_RECIPIENT, 2),
                "drawings_total": sum(r["games"][g.name]["drawings"] for r in region_results for g in GAMES),
                "cumulative_revenue": round(total_revenue_all_time, 2),
                "cumulative_payouts": round(total_payouts_all_time, 2),
            })

            results.append(month_data)

        self._save_reports(results)
        print(f"\n✅ Generation 11 simulation complete! Launching browser dashboard...")
        return results

    def _save_reports(self, results: List[Dict]):
        """Export full dataset for analysis."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(f"raffle_full_tier_sim_{timestamp}.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(f"   📁 Full CSV exported: raffle_full_tier_sim_{timestamp}.csv")


# ====================== CASINO HTML DASHBOARD ======================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>🎰 Gman's Casino MaxPlusPro v1.17</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@700;900&family=Rajdhani:wght@400;600&family=Oswald:wght@400;700&family=Bebas+Neue&display=swap');
  :root{
    --gold:#FFD700;--gold2:#FFA500;--dark:#020204;
    --nr:#ff1a44;--nb:#00ccff;--ng:#00ff66;--np:#dd00ff;--ngold:#ffee22;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  ::-webkit-scrollbar{width:5px;background:#000;}
  ::-webkit-scrollbar-thumb{background:#444;border-radius:3px;}
  body{background:#020204 url("data:image/svg+xml,%3Csvg width='60' height='60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%23ffffff' fill-opacity='.012'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/svg%3E");
    color:#e8e0c8;font-family:'Rajdhani',sans-serif;min-height:100vh;overflow-x:hidden;}

  .mbar{background:linear-gradient(90deg,#1a0005,#3d0010,#1a0005);border-bottom:3px solid var(--nr);
    box-shadow:0 0 30px var(--nr);padding:7px 0;overflow:hidden;white-space:nowrap;position:relative;z-index:10;}
  .minner{display:inline-block;animation:mar 32s linear infinite;
    font-family:'Oswald',sans-serif;font-size:1rem;letter-spacing:5px;
    color:var(--ngold);text-shadow:0 0 10px var(--gold),0 0 30px var(--gold2);}
  @keyframes mar{from{transform:translateX(100vw)}to{transform:translateX(-100%)}}

  header{text-align:center;padding:22px 16px;
    background:linear-gradient(180deg,#130026,#08001a 70%,transparent);position:relative;z-index:10;}
  .sign-frame{display:inline-block;
    background:linear-gradient(180deg,#220044,#110022);
    border:4px solid #B8860B;border-radius:14px;padding:16px 48px;
    box-shadow:0 0 50px #ff500077,0 0 120px #cc005033,inset 0 0 60px #660022aa;}
  .sign-frame h1{font-family:'Cinzel',serif;font-size:clamp(2rem,5vw,3.8rem);
    background:linear-gradient(180deg,#fffbe0,#FFD700 30%,#FFA500 65%,#994400);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    letter-spacing:6px;line-height:1.05;filter:drop-shadow(0 0 14px rgba(255,200,0,.8));animation:hf 6s ease infinite;}
  @keyframes hf{0%,88%,92%,96%,100%{opacity:1}89%,95%{opacity:.6}91%{opacity:.2}}
  .sign-sub{font-family:'Oswald',sans-serif;color:rgba(255,215,0,.5);font-size:.8rem;letter-spacing:5px;margin-top:5px;}
  .bulb-strip{display:flex;justify-content:center;gap:6px;margin:8px 0 0;}
  .blb{width:11px;height:11px;border-radius:50%;display:inline-block;box-shadow:0 0 6px currentColor;}
  .blb:nth-child(odd){color:var(--nr);background:var(--nr);animation:bc .9s infinite;}
  .blb:nth-child(even){color:var(--ngold);background:var(--ngold);animation:bc .9s .4s infinite;}
  @keyframes bc{0%,49%{opacity:1}50%,100%{opacity:.08}}
  .vpill{display:inline-block;margin-top:9px;background:rgba(255,215,0,.07);
    border:1px solid rgba(255,215,0,.3);border-radius:20px;padding:3px 14px;
    font-size:.72rem;color:var(--gold);letter-spacing:3px;font-family:'Cinzel',serif;}

  .ndiv{height:4px;background:linear-gradient(90deg,var(--nr),var(--ngold),var(--ng),var(--nb),var(--np),var(--nr));
    background-size:300% 100%;animation:rs 3s linear infinite;box-shadow:0 0 16px rgba(255,200,0,.5);position:relative;z-index:10;}
  @keyframes rs{from{background-position:0%}to{background-position:300%}}

  .live-bar{padding:14px 16px 10px;position:relative;z-index:10;}
  .live-title{font-family:'Cinzel',serif;font-size:.85rem;color:var(--ng);letter-spacing:3px;text-align:center;margin-bottom:9px;
    text-shadow:0 0 14px var(--ng);animation:gp 2s ease infinite;}
  @keyframes gp{0%,100%{text-shadow:0 0 14px var(--ng)}50%{text-shadow:0 0 28px var(--ng),0 0 60px #00ff5588}}
  .lbadge{display:inline-block;background:var(--nr);color:#fff;font-size:.58rem;letter-spacing:2px;
    padding:2px 6px;border-radius:3px;vertical-align:middle;margin-left:6px;animation:bl .8s infinite;font-weight:900;}
  @keyframes bl{0%,100%{opacity:1}50%{opacity:.15}}
  .zg{display:grid;grid-template-columns:repeat(auto-fit,minmax(115px,1fr));gap:7px;}
  .zc{background:#071209;border:1px solid rgba(0,255,80,.15);border-radius:7px;padding:9px;text-align:center;}
  .zc .zl{font-size:.58rem;letter-spacing:2px;color:#1a4428;text-transform:uppercase;margin-bottom:2px;}
  .zc .zv{font-size:1.15rem;font-weight:700;color:var(--ng);font-family:'Oswald',sans-serif;text-shadow:0 0 8px #00ff5566;}
  .pln{text-align:center;color:#1a3020;font-size:.67rem;margin-top:5px;letter-spacing:1px;}

  .ticker-wrap{background:rgba(0,0,0,.65);border-top:1px solid rgba(255,215,0,.1);
    border-bottom:1px solid rgba(255,215,0,.1);padding:6px 0;overflow:hidden;white-space:nowrap;position:relative;z-index:10;}
  .ticker-inner{display:inline-block;animation:tick 30s linear infinite;
    font-family:'Oswald',sans-serif;font-size:.8rem;letter-spacing:3px;}
  @keyframes tick{from{transform:translateX(100vw)}to{transform:translateX(-100%)}}

  /* ======= CASINO FLOOR ======= */
  .casino-floor{padding:20px 12px 30px;position:relative;z-index:10;}
  .floor-title{font-family:'Cinzel',serif;font-size:1.35rem;color:var(--gold);letter-spacing:5px;text-align:center;
    margin-bottom:28px;text-shadow:0 0 20px rgba(255,200,0,.5);}
  .floor-title span{color:var(--nr);text-shadow:0 0 16px var(--nr);}
  /* Slot-machine row — narrow cards centered */
  .machine-row{display:flex;flex-wrap:wrap;justify-content:center;gap:22px;}

  /* MACHINE */
  .machine{border-radius:18px;margin-bottom:0;overflow:visible;position:relative;
    width:340px;min-width:300px;flex-shrink:0;}
  .m-sign{border-radius:14px 14px 0 0;padding:14px 20px;text-align:center;position:relative;overflow:hidden;border:3px solid;border-bottom:none;}
  .m-sign-name{font-family:'Cinzel',serif;font-size:1.3rem;letter-spacing:4px;text-shadow:0 0 12px currentColor;position:relative;}
  .m-sign-price{font-family:'Oswald',sans-serif;font-size:2.2rem;font-weight:700;letter-spacing:2px;
    text-shadow:0 0 18px currentColor;position:relative;animation:pp 1.8s ease infinite;}
  @keyframes pp{0%,100%{filter:brightness(1)}50%{filter:brightness(1.5)}}
  .m-sign-pool{font-family:'Oswald',sans-serif;font-size:.85rem;letter-spacing:3px;opacity:.55;position:relative;margin-top:2px;}
  .m-bulbs{display:flex;gap:4px;padding:7px 14px;justify-content:center;flex-wrap:wrap;background:rgba(0,0,0,.45);border-left:3px solid;border-right:3px solid;}
  .mb{width:10px;height:10px;border-radius:50%;box-shadow:0 0 8px currentColor,0 0 16px currentColor;}
  /* Alternating flash: odd on when even off, swap at 50% */
  .mb:nth-child(odd){animation:mbo .55s ease infinite;}
  .mb:nth-child(even){animation:mbe .55s ease infinite;}
  @keyframes mbo{0%,49%{opacity:1;filter:brightness(1.8)}50%,100%{opacity:.06;filter:brightness(.3)}}
  @keyframes mbe{0%,49%{opacity:.06;filter:brightness(.3)}50%,100%{opacity:1;filter:brightness(1.8)}}

  .m-body{border:3px solid;border-top:none;border-radius:0 0 16px 16px;
    background:radial-gradient(ellipse at 50% 20%,#0d3d1a,#061a0c 55%,#030d06);
    position:relative;overflow:hidden;}
  .m-body::before{content:'';position:absolute;inset:0;pointer-events:none;
    background:repeating-linear-gradient(0deg,transparent,transparent 28px,rgba(0,0,0,.04) 28px,rgba(0,0,0,.04) 29px),
               repeating-linear-gradient(90deg,transparent,transparent 28px,rgba(0,0,0,.04) 28px,rgba(0,0,0,.04) 29px);}
  .m-inner{padding:16px 18px;position:relative;z-index:1;}

  /* REEL DISPLAY */
  .reel-box{background:#000;border-radius:12px;border:3px solid rgba(255,215,0,.2);
    padding:12px;margin-bottom:14px;position:relative;overflow:hidden;
    box-shadow:inset 0 0 40px rgba(0,0,0,.95),0 0 20px rgba(0,0,0,.5);}
  .reel-box::before{content:'';position:absolute;inset:0;
    background:linear-gradient(180deg,rgba(0,0,0,.7) 0%,transparent 20%,transparent 80%,rgba(0,0,0,.7) 100%);
    pointer-events:none;z-index:3;}
  .reel-box::after{content:'';position:absolute;left:10px;right:10px;top:50%;height:3px;
    background:linear-gradient(90deg,transparent,var(--gold),transparent);
    box-shadow:0 0 12px var(--gold);transform:translateY(-50%);pointer-events:none;z-index:4;}
  .reel-row{display:flex;justify-content:center;gap:4px;align-items:stretch;}
  .reel{width:64px;height:80px;overflow:hidden;position:relative;
    background:#0a0a0a;border:1px solid rgba(255,255,255,.06);border-radius:6px;}
  .reel-strip{position:absolute;top:0;left:0;width:100%;transition:none;}
  .reel-cell{height:80px;display:flex;align-items:center;justify-content:center;
    font-size:2.2rem;user-select:none;}
  .reel-sep{width:3px;background:rgba(255,215,0,.1);border-radius:2px;align-self:stretch;}


  .play-area{text-align:center;margin:14px 0;}
  .btn-pull{padding:12px 36px;border:none;border-radius:9px;cursor:pointer;
    font-family:'Cinzel',serif;font-size:1rem;font-weight:700;letter-spacing:3px;
    transition:all .1s;box-shadow:0 4px 20px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.15);position:relative;overflow:hidden;}
  .btn-pull::before{content:'';position:absolute;inset:0;
    background:linear-gradient(135deg,rgba(255,255,255,.15),transparent 50%);}
  .btn-pull:hover{filter:brightness(1.25);transform:translateY(-2px);}
  .btn-pull:active{transform:translateY(2px);filter:brightness(.85);}
  .btn-pull:disabled{opacity:.35;cursor:not-allowed;transform:none;filter:none;}
  .pull-result{min-height:22px;text-align:center;font-family:'Oswald',sans-serif;font-size:.82rem;letter-spacing:2px;margin-bottom:10px;}

  /* GRID LAYOUT — stacked inside narrow machine card */
  .m-grid{display:grid;grid-template-columns:1fr;gap:12px;}

  .stats-panel{background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.05);border-radius:9px;padding:12px;}
  .sp-row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:.85rem;}
  .sp-row:last-child{border-bottom:none;}
  .sp-l{color:rgba(255,255,255,.33);font-size:.73rem;letter-spacing:1px;}
  .sp-v{font-weight:700;color:#eee;}
  .sp-v.hl{color:var(--gold);text-shadow:0 0 6px rgba(255,200,0,.35);}
  .prog-wrap{margin-top:10px;}
  .prog-lbl{display:flex;justify-content:space-between;font-size:.6rem;letter-spacing:2px;color:rgba(255,255,255,.25);margin-bottom:3px;}
  .prog-bg{height:7px;background:rgba(0,0,0,.6);border-radius:4px;overflow:hidden;border:1px solid rgba(255,255,255,.04);}
  .prog-fill{height:100%;border-radius:4px;transition:width .5s;position:relative;}
  .prog-fill::after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.25),transparent);animation:sh 2s infinite;}
  @keyframes sh{from{transform:translateX(-100%)}to{transform:translateX(100%)}}
  .rw-panel{margin-top:10px;background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.04);border-radius:7px;padding:8px;}
  .rw-title{font-family:'Cinzel',serif;font-size:.65rem;color:rgba(255,215,0,.4);letter-spacing:2px;margin-bottom:5px;text-align:center;}
  .rw-row{display:flex;align-items:center;gap:8px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.03);font-size:.7rem;}
  .rw-row:last-child{border-bottom:none;}
  .rw-tk{color:var(--gold);font-family:'Oswald',sans-serif;font-weight:700;}
  .rw-amt{font-family:'Oswald',sans-serif;}
  .rw-time{color:rgba(255,255,255,.2);font-size:.6rem;margin-left:auto;}

  /* BUY PANEL */
  .buy-panel{background:rgba(0,0,0,.35);border:1px solid rgba(255,215,0,.1);border-radius:9px;padding:13px;}
  .bp-title{font-family:'Cinzel',serif;font-size:.78rem;color:var(--gold);letter-spacing:2px;text-align:center;margin-bottom:9px;}
  .bp-row{display:flex;gap:8px;align-items:center;margin-bottom:7px;}
  .bp-lbl{font-size:.7rem;letter-spacing:1px;color:rgba(255,255,255,.36);min-width:48px;}
  .bp-inp{flex:1;background:rgba(0,0,0,.55);border:1px solid rgba(255,215,0,.2);border-radius:5px;
    color:var(--gold);font-size:.95rem;font-family:'Oswald',sans-serif;padding:5px 7px;outline:none;text-align:center;}
  .bp-inp:focus{border-color:var(--gold);}
  .bp-cost{text-align:center;font-size:.75rem;color:rgba(255,255,255,.3);margin-bottom:7px;}
  .bp-cost span{color:var(--gold);font-weight:700;}
  .bp-buy{width:100%;padding:10px;border:none;border-radius:7px;cursor:pointer;
    font-family:'Cinzel',serif;font-size:.85rem;font-weight:700;letter-spacing:2px;transition:all .1s;}
  .bp-buy:hover{filter:brightness(1.2);transform:translateY(-1px);}
  .bp-buy:active{transform:translateY(1px);}
  .bp-gift{width:100%;padding:7px;margin-top:5px;border-radius:6px;border:none;cursor:pointer;
    background:linear-gradient(135deg,#150040,#3800aa,#150040);border:1px solid rgba(130,40,255,.35);
    font-family:'Cinzel',serif;font-size:.74rem;font-weight:700;color:#bb88ff;letter-spacing:2px;transition:all .1s;}
  .bp-gift:hover{filter:brightness(1.2);}
  .bp-result{margin-top:7px;padding:6px 8px;border-radius:6px;font-size:.76rem;text-align:center;display:none;
    font-family:'Oswald',sans-serif;letter-spacing:1px;}
  .bp-result.show{display:block;}
  .bp-result.ok{background:rgba(0,150,50,.1);border:1px solid rgba(0,255,80,.18);color:#00ff88;}
  .bp-result.gk{background:rgba(100,0,180,.1);border:1px solid rgba(160,40,255,.18);color:#bb88ff;}
  .my-tix{margin-top:8px;min-height:28px;padding:6px;background:rgba(0,0,0,.2);
    border:1px dashed rgba(255,215,0,.12);border-radius:6px;}
  .mx-ttl{font-size:.58rem;letter-spacing:2px;color:rgba(255,215,0,.25);text-transform:uppercase;margin-bottom:3px;text-align:center;}
  .tkt{display:inline-block;margin:2px;font-size:.62rem;color:var(--gold);font-family:'Oswald',sans-serif;
    letter-spacing:1px;background:rgba(255,215,0,.07);border:1px solid rgba(255,215,0,.22);
    border-radius:3px;padding:2px 5px;animation:tp .2s ease;}
  @keyframes tp{from{transform:scale(0)}80%{transform:scale(1.1)}to{transform:scale(1)}}
  .tkt.g{color:#bb88ff;background:rgba(120,0,220,.07);border-color:rgba(150,40,255,.22);}

  .win-overlay{position:fixed;inset:0;z-index:9999;display:none;background:rgba(0,0,0,.7);align-items:center;justify-content:center;}
  .win-overlay.show{display:flex;}
  .win-box{background:linear-gradient(135deg,#1c0035,#2e0055);border:3px solid var(--gold);border-radius:16px;
    padding:28px 38px;text-align:center;box-shadow:0 0 60px rgba(255,200,0,.5);animation:popIn .3s ease;max-width:420px;width:90%;}
  @keyframes popIn{from{transform:scale(0)}80%{transform:scale(1.05)}to{transform:scale(1)}}
  .win-box h2{font-family:'Cinzel',serif;font-size:2rem;
    background:linear-gradient(135deg,#fff8a0,var(--gold),var(--gold2));
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px;
    filter:drop-shadow(0 0 8px rgba(255,200,0,.6));}
  .win-box p{font-family:'Oswald',sans-serif;font-size:.95rem;color:#ccc;letter-spacing:2px;line-height:1.6;}
  .win-close{margin-top:14px;background:linear-gradient(135deg,#aa7000,#FFD700,#aa7000);
    color:#1a0800;border:none;border-radius:7px;padding:8px 24px;cursor:pointer;
    font-family:'Cinzel',serif;font-size:.85rem;letter-spacing:2px;font-weight:700;}

  .charts-toggle{display:block;width:100%;padding:12px;position:relative;z-index:10;
    background:rgba(255,215,0,.03);border:none;border-top:1px solid rgba(255,215,0,.06);border-bottom:1px solid rgba(255,215,0,.06);
    color:rgba(255,215,0,.3);font-family:'Cinzel',serif;font-size:.78rem;letter-spacing:2px;cursor:pointer;text-align:center;}
  .charts-toggle:hover{background:rgba(255,215,0,.07);color:rgba(255,215,0,.6);}
  .charts-body{display:none;padding:14px;position:relative;z-index:10;}
  .charts-body.open{display:block;}
  .cr{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;}
  @media(max-width:700px){.cr{grid-template-columns:1fr;}}
  .cc{background:#060c12;border:1px solid rgba(255,215,0,.05);border-radius:8px;padding:12px;}
  .cc h3{font-family:'Cinzel',serif;font-size:.72rem;color:rgba(255,215,0,.3);letter-spacing:2px;margin-bottom:7px;}
  .sw{display:flex;align-items:center;gap:10px;margin-bottom:12px;}
  #monthSlider{flex:1;-webkit-appearance:none;height:5px;background:linear-gradient(90deg,var(--ng),var(--gold),var(--nr));border-radius:3px;outline:none;cursor:pointer;}
  #monthSlider::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;border-radius:50%;background:var(--gold);cursor:pointer;}
  #monthLabel{color:var(--gold);font-size:.8rem;font-family:'Oswald',sans-serif;}
  .sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:7px;margin-bottom:12px;}
  .sc-s{background:#060c12;border:1px solid rgba(255,215,0,.05);border-radius:7px;padding:9px;text-align:center;}
  .sc-s .sl{font-size:.56rem;letter-spacing:2px;color:#2a3040;text-transform:uppercase;margin-bottom:2px;}
  .sc-s .sv{font-size:1.15rem;font-weight:700;font-family:'Oswald',sans-serif;}
  .sv.go{color:var(--gold)}.sv.gr{color:var(--ng)}.sv.bl{color:var(--nb)}.sv.rd{color:var(--nr)}.sv.pu{color:var(--np)}
  .jp-strip{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin-bottom:10px;}
  .jp{background:#120022;border:1px solid rgba(255,215,0,.18);border-radius:18px;padding:4px 12px;font-size:.72rem;}
  .jp span{color:var(--gold);font-weight:700;font-family:'Oswald',sans-serif;}
  .about-sec{padding:18px 14px;position:relative;z-index:10;}
  .about-t{font-family:'Cinzel',serif;font-size:.95rem;color:var(--gold);letter-spacing:3px;text-align:center;margin-bottom:12px;}
  .ag{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;}
  .ac{background:#060c12;border:1px solid rgba(255,215,0,.05);border-radius:9px;padding:14px;}
  .ac h3{font-family:'Cinzel',serif;font-size:.82rem;margin-bottom:6px;}
  .ac p,.ac li{font-size:.8rem;color:#607080;line-height:1.65;}
  .ac li{margin-bottom:2px;}.ac ul{padding-left:12px;}.ac li span{color:var(--gold);font-weight:700;}
  footer{text-align:center;padding:12px;color:#151515;font-size:.68rem;position:relative;z-index:10;}

  /* DIRECT DEPOSIT MODAL */
  .dd-modal{display:none;position:fixed;inset:0;z-index:20000;align-items:center;justify-content:center;background:rgba(0,0,0,.82);backdrop-filter:blur(4px);}
  .dd-modal.open{display:flex;}
  .dd-box{background:linear-gradient(160deg,#0a1a0e,#091420);border:2px solid var(--gold);border-radius:16px;padding:28px 30px;max-width:480px;width:92%;box-shadow:0 0 60px rgba(255,215,0,.25);}
  .dd-box h3{font-family:'Cinzel',serif;color:var(--gold);font-size:1.05rem;letter-spacing:3px;margin-bottom:6px;text-align:center;}
  .dd-sub{font-size:.72rem;color:rgba(255,255,255,.35);text-align:center;margin-bottom:18px;letter-spacing:1px;}
  .dd-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;}
  .dd-grid.full{grid-template-columns:1fr;}
  .dd-field{display:flex;flex-direction:column;gap:4px;}
  .dd-field label{font-size:.65rem;color:rgba(255,255,255,.38);letter-spacing:1px;}
  .dd-field input,.dd-field select{background:rgba(0,0,0,.55);border:1px solid rgba(255,215,0,.22);border-radius:6px;
    color:#eee;font-size:.88rem;font-family:'Oswald',sans-serif;padding:7px 9px;outline:none;}
  .dd-field input:focus,.dd-field select:focus{border-color:var(--gold);}
  .dd-notice{background:rgba(255,60,0,.06);border:1px solid rgba(255,80,0,.2);border-radius:7px;padding:9px 12px;
    font-size:.68rem;color:rgba(255,160,80,.7);margin-bottom:14px;line-height:1.6;}
  .dd-actions{display:flex;gap:10px;}
  .dd-confirm{flex:1;padding:11px;border:none;border-radius:8px;cursor:pointer;
    background:linear-gradient(135deg,#886600,#FFD700,#886600);color:#1a0800;
    font-family:'Cinzel',serif;font-size:.85rem;font-weight:700;letter-spacing:2px;}
  .dd-confirm:hover{filter:brightness(1.15);}
  .dd-cancel{padding:11px 16px;border:1px solid rgba(255,255,255,.1);border-radius:8px;
    background:rgba(255,255,255,.04);color:rgba(255,255,255,.4);cursor:pointer;
    font-family:'Oswald',sans-serif;font-size:.8rem;}
  /* DD section inside buy panel */
  .dd-toggle{width:100%;padding:7px;margin-top:6px;border-radius:6px;
    background:rgba(0,80,80,.25);border:1px solid rgba(0,220,200,.18);
    color:#00ddcc;font-family:'Oswald',sans-serif;font-size:.72rem;letter-spacing:2px;cursor:pointer;}
  .dd-toggle:hover{filter:brightness(1.2);}
  .dd-inline{display:none;margin-top:8px;padding:10px;background:rgba(0,0,0,.3);border:1px solid rgba(0,220,200,.12);border-radius:7px;}
  .dd-inline.open{display:block;}
  .dd-inline label{font-size:.62rem;color:rgba(255,255,255,.3);letter-spacing:1px;display:block;margin-bottom:2px;margin-top:6px;}
  .dd-inline input,.dd-inline select{width:100%;background:rgba(0,0,0,.5);border:1px solid rgba(0,220,200,.2);
    border-radius:5px;color:#eee;font-size:.8rem;font-family:'Oswald',sans-serif;padding:5px 8px;outline:none;margin-bottom:1px;}
  .dd-inline input:focus{border-color:#00ddcc;}
  .dd-inline .dd-note{font-size:.6rem;color:rgba(255,200,0,.4);margin-top:5px;line-height:1.5;}
</style>
</head>
<body>
<!-- DIRECT DEPOSIT MODAL -->
<div class="dd-modal" id="ddModal">
  <div class="dd-box">
    <h3>🏦 PAYOUT DIRECT DEPOSIT</h3>
    <div class="dd-sub" id="dd-modal-sub">YOUR WINNING DEPOSIT INFORMATION</div>
    <div class="dd-notice">⚠ Pre-launch — no real money transfers occur. This information is collected for when real payments go live. All data is stored locally only.</div>
    <div class="dd-grid">
      <div class="dd-field"><label>FULL LEGAL NAME</label><input id="dd-name" placeholder="As on bank account"></div>
      <div class="dd-field"><label>EMAIL</label><input id="dd-email" type="email" placeholder="For confirmation"></div>
    </div>
    <div class="dd-grid">
      <div class="dd-field"><label>BANK NAME</label><input id="dd-bank" placeholder="e.g. Chase, Wells Fargo"></div>
      <div class="dd-field"><label>ACCOUNT TYPE</label>
        <select id="dd-acct-type"><option value="checking">Checking</option><option value="savings">Savings</option></select>
      </div>
    </div>
    <div class="dd-grid">
      <div class="dd-field"><label>ROUTING NUMBER (9 digits)</label><input id="dd-routing" placeholder="e.g. 021000021" maxlength="9"></div>
      <div class="dd-field"><label>ACCOUNT NUMBER</label><input id="dd-account" placeholder="Your account #"></div>
    </div>
    <div class="dd-notice" id="dd-gift-notice" style="display:none;background:rgba(150,0,255,.07);border-color:rgba(180,80,255,.25);color:rgba(200,140,255,.8);">🎁 GIFTING: The recipient will be asked to provide their own deposit info when they claim their ticket. These details are yours as the purchaser — you will receive any payout if gift claim expires.</div>
    <div class="dd-actions">
      <button class="dd-cancel" onclick="closeDDModal()">CANCEL</button>
      <button class="dd-confirm" id="dd-confirm-btn">✅ CONFIRM &amp; PURCHASE</button>
    </div>
  </div>
</div>
<canvas id="confettiCanvas" style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;"></canvas>
<div id="flashOverlay" style="position:fixed;inset:0;pointer-events:none;z-index:9998;opacity:0;transition:opacity .08s;"></div>
<div class="win-overlay" id="winOverlay">
  <div class="win-box"><h2 id="winTitle">🎉 WINNER!</h2><p id="winMsg"></p>
    <button class="win-close" onclick="closeWin()">💰 COLLECT WINNINGS</button></div>
</div>
<button id="musicBtn" onclick="toggleMusic()" style="position:fixed;bottom:18px;right:18px;z-index:10000;background:rgba(0,0,0,.75);border:1px solid #FFD700;color:#FFD700;font-size:.75rem;padding:8px 14px;border-radius:20px;cursor:pointer;letter-spacing:2px;font-family:'Oswald',sans-serif;">🎵 MUSIC: OFF</button>
<div class="mbar"><span class="minner">
  🎰 GMAN'S CASINO MAXPLUS PRO v1.17 ★ 5 RAFFLE GAMES ★ BUY UP TO 10 TICKETS ★ GIFT TO FRIENDS ★ 1,000,000 TICKETS = DRAWING ★ MONTHLY ANNUITY ★ 25% TAX WITHHELD ★ ANTI-FRAUD HMAC TICKET SYSTEM ★ SEQUENTIAL NUMBERING 1–1,000,000 ★
</span></div>
<header>
  <div class="sign-frame">
    <h1>🎰 Gman's Casino<br>MaxPlusPro</h1>
    <div class="sign-sub">GLOBAL MULTI-TIER RAFFLE · GENERATION 11</div>
    <div class="bulb-strip">
      <span class="blb"></span><span class="blb"></span><span class="blb"></span><span class="blb"></span>
      <span class="blb"></span><span class="blb"></span><span class="blb"></span><span class="blb"></span>
      <span class="blb"></span><span class="blb"></span><span class="blb"></span><span class="blb"></span>
      <span class="blb"></span><span class="blb"></span><span class="blb"></span><span class="blb"></span>
      <span class="blb"></span><span class="blb"></span><span class="blb"></span><span class="blb"></span>
    </div>
  </div>
  <div><div class="vpill">v1.17 · RAFFLE CASINO · HMAC ANTI-FRAUD · PRE-LAUNCH</div></div>
</header>
<div class="ndiv"></div>
<div class="live-bar">
  <div class="live-title">📡 LIVE SYSTEM STATS <span class="lbadge">LIVE</span></div>
  <div class="zg">
    <div class="zc"><div class="zl">Users</div><div class="zv" id="lv-users">0</div></div>
    <div class="zc"><div class="zl">Tickets Sold</div><div class="zv" id="lv-tickets">0</div></div>
    <div class="zc"><div class="zl">Revenue</div><div class="zv" id="lv-revenue">$0</div></div>
    <div class="zc"><div class="zl">Payouts</div><div class="zv" id="lv-payouts">$0</div></div>
    <div class="zc"><div class="zl">Winners</div><div class="zv" id="lv-winners">0</div></div>
    <div class="zc"><div class="zl">Drawings</div><div class="zv" id="lv-drawings">0</div></div>
  </div>
  <div class="pln">⚠ Pre-launch. Live stats update when real tickets are purchased via API.</div>
</div>
<div class="ndiv"></div>
<div class="ticker-wrap"><span class="ticker-inner" id="tickerInner"></span></div>
<div class="casino-floor">
  <div class="floor-title">🎰 THE <span>CASINO FLOOR</span> — 5 RAFFLE GAMES</div>
  <div class="machine-row" id="floorArea"></div>
</div>
<div class="ndiv"></div>
<button class="charts-toggle" onclick="toggleCharts()">📊 View Projected Scale Simulation ▼</button>
<div class="charts-body" id="chartsBody">
  <div class="jp-strip" id="jackpotStrip"></div>
  <div class="sg" id="statsGrid"></div>
  <div class="sw"><input type="range" id="monthSlider" min="1" max="{{ months }}" value="{{ months }}"><div id="monthLabel">Month {{ months }}</div></div>
  <div class="cr"><div class="cc"><h3>💰 Revenue vs Payouts</h3><canvas id="revChart"></canvas></div><div class="cc"><h3>🎟 Recipients</h3><canvas id="recipChart"></canvas></div></div>
  <div class="cr"><div class="cc"><h3>📈 Cumulative</h3><canvas id="cumChart"></canvas></div><div class="cc"><h3>🎯 Tier Split</h3><canvas id="tierPieChart"></canvas></div></div>
</div>
<div class="about-sec">
  <div class="about-t">📖 About Gman's Casino MaxPlusPro v1.17</div>
  <div class="ag">
    <div class="ac"><h3 style="color:#FFD700;">🎯 What Is This?</h3><p>Global multi-tier raffle. Tickets sequentially numbered 1–1,000,000. HMAC-SHA256 anti-fraud. Drawing fires at exactly 1M tickets. Winners paid monthly annuity. 25% tax. Handles billions of micro-transactions globally.</p></div>
    <div class="ac"><h3 style="color:#00ccff;">🎟 5 Games</h3><ul>
      <li><span>$0.25</span> — 5 winners · $8,333/mo × 6mo · $250K pool</li>
      <li><span>$4</span> — 80 winners · $8,333/mo × 6mo · $4M pool</li>
      <li><span>$10</span> — 25 winners · $33,333/mo × 12mo · $10M pool</li>
      <li><span>$100</span> — 200 winners · $83,333/mo × 12mo · $100M pool</li>
      <li><span>$1,000</span> — 2,000 winners · $20,833/mo × 24mo · $1B pool</li></ul></div>
    <div class="ac"><h3 style="color:#00ff66;">🔐 Anti-Fraud</h3><p>Every ticket has: sequential ID (1–1M), HMAC-SHA256 signature, owner binding, timestamp. Tickets cannot be forged, duplicated, or transferred without cryptographic proof.</p></div>
    <div class="ac"><h3 style="color:#ff1a44;">💸 Rules</h3><ul>
      <li>Max <span>10 tickets</span> per person per game</li>
      <li>Gift up to <span>10</span> to a friend</li>
      <li>Drawing at <span>1,000,000</span> tickets</li>
      <li><span>25%</span> tax withheld</li>
      <li>SystemRandom for winner selection</li></ul></div>
  </div>
</div>
<footer>🎰 Gman's Casino MaxPlusPro v1.17 — Sequential Ticketing — HMAC Anti-Fraud — Pre-Launch Concept</footer>

<script>
const SIM = {{ sim_data | tojson }};
const GAMES_DATA = {{ games_data | tojson }};
const TC=['#FFD700','#00ddff','#00ff55','#cc44ff','#ff1a44'];

/* ===== AUDIO ENGINE ===== */
let AC=null;
function getAC(){if(!AC){AC=new(window.AudioContext||window.webkitAudioContext)();}if(AC.state==='suspended')AC.resume();return AC;}
function tone(f,t,v,d,dl=0){try{const a=getAC(),s=a.currentTime+dl,o=a.createOscillator(),g=a.createGain();o.connect(g);g.connect(a.destination);o.type=t;o.frequency.setValueAtTime(f,s);g.gain.setValueAtTime(0,s);g.gain.linearRampToValueAtTime(v,s+.015);g.gain.exponentialRampToValueAtTime(.001,s+d);o.start(s);o.stop(s+d+.05);}catch(e){}}

/* Reel stop clunk */
function sndReelStop(i){tone(180+i*40,'square',.22,.08);tone(90+i*20,'sine',.18,.12,.04);}

/* Coin cascade */
function sndCoin(){for(let i=0;i<8;i++){tone(880+Math.random()*400,'sine',.13,.18,i*.055);}}

/* Near-miss descending womp */
function sndNear(){[320,240,180,130].forEach((f,i)=>tone(f,'sawtooth',.15,.22,i*.11));}

/* Small win jingle */
function sndSmallWin(){[523,659,784,523,659,784,1047].forEach((f,i)=>tone(f,'sine',.18,.35,i*.09));}

/* Big jackpot fanfare */
function sndJackpot(){
  [523,659,784,1047,1319,1568,2093].forEach((f,i)=>tone(f,'sine',.25,.6,i*.11));
  [392,494,587,784].forEach((f,i)=>tone(f,'triangle',.2,.5,i*.14+.05));
  setTimeout(()=>{for(let i=0;i<12;i++)tone(440+Math.random()*900,'sine',.12,.3,i*.06);},700);
}

/* ===== CASINO MUSIC (Web Audio synth loop) ===== */
let musicOn=false,musicNodes=[];
function buildMusicLoop(){
  const a=getAC();
  const master=a.createGain();master.gain.value=0.09;master.connect(a.destination);
  /* Simple casino-style progression: I-IV-V-I in C */
  const prog=[[261,329,392],[349,440,523],[392,494,587],[261,329,392,523]];
  let step=0;
  function playChord(){
    if(!musicOn)return;
    const now=a.currentTime;
    prog[step%prog.length].forEach((f,i)=>{
      const o=a.createOscillator(),g=a.createGain();
      o.type='triangle';o.frequency.value=f;
      g.gain.setValueAtTime(0,now);g.gain.linearRampToValueAtTime(.35,now+.06);
      g.gain.setValueAtTime(.35,now+.55);g.gain.linearRampToValueAtTime(0,now+.75);
      o.connect(g);g.connect(master);
      o.start(now);o.stop(now+.8);
    });
    /* walking bass */
    const bass=[130,87,98,130];
    const ob=a.createOscillator(),gb=a.createGain();
    ob.type='sine';ob.frequency.value=bass[step%bass.length];
    gb.gain.setValueAtTime(.5,now);gb.gain.exponentialRampToValueAtTime(.001,now+.7);
    ob.connect(gb);gb.connect(master);ob.start(now);ob.stop(now+.75);
    step++;
    if(musicOn) setTimeout(playChord,750);
  }
  musicNodes=[master];
  playChord();
}
function toggleMusic(){
  musicOn=!musicOn;
  document.getElementById('musicBtn').textContent=musicOn?'🎵 MUSIC: ON':'🎵 MUSIC: OFF';
  if(musicOn){try{getAC().resume().then(buildMusicLoop);}catch(e){buildMusicLoop();}}
  else{musicNodes.forEach(n=>{try{n.disconnect();}catch(e){}});musicNodes=[];}
}
document.addEventListener('click',()=>{try{getAC().resume();}catch(e){}},{once:true});

/* ===== CONFETTI ===== */
const confCvs=document.getElementById('confettiCanvas');
const confCtx=confCvs.getContext('2d');
let confParts=[],confRunning=false;
function resizeConf(){confCvs.width=window.innerWidth;confCvs.height=window.innerHeight;}
window.addEventListener('resize',resizeConf);resizeConf();
function spawnConfetti(n,colors){
  for(let i=0;i<n;i++){
    confParts.push({
      x:Math.random()*confCvs.width,y:-10,
      vx:(Math.random()-0.5)*6,vy:Math.random()*4+2,
      rot:Math.random()*360,rotV:(Math.random()-0.5)*8,
      w:Math.random()*10+5,h:Math.random()*5+3,
      color:colors[Math.floor(Math.random()*colors.length)],
      life:1
    });
  }
  if(!confRunning){confRunning=true;rafConf();}
}
function rafConf(){
  confCtx.clearRect(0,0,confCvs.width,confCvs.height);
  confParts=confParts.filter(p=>p.life>0);
  confParts.forEach(p=>{
    p.x+=p.vx;p.y+=p.vy;p.vy+=0.07;p.rot+=p.rotV;p.life-=0.006;
    confCtx.save();confCtx.globalAlpha=p.life;
    confCtx.translate(p.x,p.y);confCtx.rotate(p.rot*Math.PI/180);
    confCtx.fillStyle=p.color;
    confCtx.fillRect(-p.w/2,-p.h/2,p.w,p.h);
    confCtx.restore();
  });
  if(confParts.length>0) requestAnimationFrame(rafConf);
  else confRunning=false;
}

/* ===== SCREEN FLASH ===== */
function flashScreen(color,dur=180){
  const el=document.getElementById('flashOverlay');
  el.style.background=color;el.style.opacity='0.45';
  setTimeout(()=>el.style.opacity='0',dur);
}

/* ===== WIN OVERLAY ===== */
function showWin(t,m){
  document.getElementById('winTitle').textContent=t;
  document.getElementById('winMsg').textContent=m;
  document.getElementById('winOverlay').className='win-overlay show';
}
function closeWin(){document.getElementById('winOverlay').className='win-overlay';}

/* ===== TICKER ===== */
const WMSGS=['🏆 #0000482 WON $50,000!','🎟 Player bought 10 tickets!','🎁 5 tickets gifted!','💰 #0912004 entered $1K Elite!','🏆 #0774332 receives $8,333/mo!','⚡ Golden Vault: 12K to drawing!','🎟 #0338810 entered Green Giant!','💸 #0552019 collecting $33,333/mo!','🔥 ALL IN on $1B game!','🏆 #0887123 — $1M annuity!'];
function refreshTicker(){
  const s=[...WMSGS].sort(()=>Math.random()-.5);
  document.getElementById('tickerInner').innerHTML=s.map(t=>`<span style="color:${['#FFD700','#00ff66','#00ccff','#dd00ff','#ff1a44'][Math.floor(Math.random()*5)]}">${t}</span>`).join(' ★ ');
}
refreshTicker();setInterval(refreshTicker,30000);

/* ===== TRADITIONAL SLOT SYMBOLS ===== */
const SYMBOLS_BY_TIER = {
  '025':  ['🍒','🍋','🔔','⭐','7️⃣'],           // 3 reels
  '4':    ['🍒','💎','🔔','⭐','7️⃣','🍀'],       // 3 reels
  '10':   ['🍒','💎','🔔','⭐','7️⃣','🍀','👑'],  // 4 reels
  '100':  ['🍒','💎','🔔','⭐','7️⃣','🍀','👑','💰'], // 5 reels
  '1000': ['🍒','💎','🔔','⭐','7️⃣','🍀','👑','💰','🎰','🏆'], // 6 reels
};

/* ===== GAME DEFINITIONS ===== */
const G=[
  {id:'025',price:.25,label:'$0.25',name:'QUARTER RUSH',winners:5,payout:'$8,333/mo',dur:'6 months',total:'$50,000',pool:'$250,000',
   accent:'#b8ff44',border:'#2a6600',glow:'#55bb00',reels:3,
   btnBg:'linear-gradient(135deg,#2a5500,#66cc00,#2a5500)',btnC:'#fff',
   chipBg:'linear-gradient(135deg,#1a3a00,#306000)',chipTxt:'25¢'},
  {id:'4',price:4,label:'$4',name:'BLUE DIAMOND',winners:80,payout:'$8,333/mo',dur:'6 months',total:'$50,000',pool:'$4,000,000',
   accent:'#00ccff',border:'#004488',glow:'#0077cc',reels:3,
   btnBg:'linear-gradient(135deg,#002244,#0077cc,#002244)',btnC:'#fff',
   chipBg:'linear-gradient(135deg,#001830,#003366)',chipTxt:'$4'},
  {id:'10',price:10,label:'$10',name:'GREEN GIANT',winners:25,payout:'$33,333/mo',dur:'12 months',total:'$400,000',pool:'$10,000,000',
   accent:'#00ff66',border:'#006622',glow:'#00aa44',reels:4,
   btnBg:'linear-gradient(135deg,#004422,#00bb44,#004422)',btnC:'#fff',
   chipBg:'linear-gradient(135deg,#003318,#005522)',chipTxt:'$10'},
  {id:'100',price:100,label:'$100',name:'GOLDEN VAULT',winners:200,payout:'$83,333/mo',dur:'12 months',total:'$1,000,000',pool:'$100,000,000',
   accent:'#FFD700',border:'#886600',glow:'#FFD700',reels:5,
   btnBg:'linear-gradient(135deg,#886600,#FFD700,#886600)',btnC:'#1a0800',
   chipBg:'linear-gradient(135deg,#3a2400,#664000)',chipTxt:'$100'},
  {id:'1000',price:1000,label:'$1,000',name:'BILLION DOLLAR ELITE',winners:2000,payout:'$20,833/mo',dur:'24 months',total:'$500,000',pool:'$1,000,000,000',
   accent:'#ff1a44',border:'#880022',glow:'#ff1a44',reels:6,
   btnBg:'linear-gradient(135deg,#880022,#ff1a44,#880022)',btnC:'#fff',
   chipBg:'linear-gradient(135deg,#380010,#660020)',chipTxt:'$1K'},
];

const GS={};
G.forEach(g=>{GS[g.id]={myTickets:[],recentWins:[],spinning:false,spins:0,progress:0};});

/* Player identity (stored in localStorage) */
let PLAYER_ID = localStorage.getItem('casino_player_id');
if(!PLAYER_ID){PLAYER_ID='P'+Date.now().toString(36)+Math.random().toString(36).substr(2,6);localStorage.setItem('casino_player_id',PLAYER_ID);}

/* ===== BUILD REELS ===== */
function buildReelStrip(gid){
  const syms=SYMBOLS_BY_TIER[gid];
  let cells='';
  for(let j=0;j<30;j++) cells+=`<div class="reel-cell">${syms[Math.floor(Math.random()*syms.length)]}</div>`;
  return cells;
}

function buildMachine(g){
  const pct=GS[g.id].progress.toFixed(1);
  let reelsHTML='';
  for(let i=0;i<g.reels;i++){
    if(i>0)reelsHTML+=`<div class="reel-sep"></div>`;
    reelsHTML+=`<div class="reel" id="reel-${g.id}-${i}"><div class="reel-strip" id="rs-${g.id}-${i}">${buildReelStrip(g.id)}</div></div>`;
  }
  let bulbs='';
  for(let i=0;i<18;i++)bulbs+=`<div class="mb" style="color:${g.accent};background:${g.accent};animation:bc ${.7+i%3*.25}s ${i*.06}s infinite;"></div>`;

  return `
  <div class="machine">
    <div class="m-sign" style="border-color:${g.border};background:linear-gradient(180deg,rgba(0,0,0,.7),rgba(0,0,0,.4));box-shadow:0 0 40px ${g.glow}44,inset 0 0 30px rgba(0,0,0,.5);">
      <div class="m-sign-name" style="color:${g.accent}">${g.name}</div>
      <div class="m-sign-price" style="color:${g.accent}">${g.label} ENTRY</div>
      <div class="m-sign-pool">PRIZE POOL: ${g.pool} · ${g.reels} REELS</div>
    </div>
    <div class="m-bulbs" style="border-color:${g.border}">${bulbs}</div>
    <div class="m-body" style="border-color:${g.border};box-shadow:0 0 50px ${g.glow}22;">
      <div class="m-inner">
        <!-- REELS -->
        <div class="reel-box" style="border-color:${g.accent}33;">
          <div class="reel-row">${reelsHTML}</div>
        </div>
        <div class="play-area">
          <button class="btn-pull" id="pull-${g.id}" style="background:${g.btnBg};color:${g.btnC};box-shadow:0 0 25px ${g.glow}55;"
            onclick="doPull('${g.id}')">🎰 PULL — SPIN ${g.reels} REELS</button>
        </div>
        <div class="pull-result" id="pr-${g.id}"></div>
        <div class="m-grid">
          <div>
            <div class="stats-panel">
              <div class="sp-row"><span class="sp-l">Winners / Drawing</span><span class="sp-v hl" style="color:${g.accent}">${g.winners.toLocaleString()}</span></div>
              <div class="sp-row"><span class="sp-l">Monthly Payout</span><span class="sp-v hl">${g.payout}</span></div>
              <div class="sp-row"><span class="sp-l">Duration</span><span class="sp-v">${g.dur}</span></div>
              <div class="sp-row"><span class="sp-l">Total / Winner</span><span class="sp-v hl">${g.total}</span></div>
              <div class="sp-row"><span class="sp-l">Reels</span><span class="sp-v">${g.reels} (match all = jackpot)</span></div>
              <div class="prog-wrap">
                <div class="prog-lbl"><span id="ptl-${g.id}">Tickets: 0 / 1,000,000</span><span style="color:${g.accent}" id="pct-${g.id}">0%</span></div>
                <div class="prog-bg"><div class="prog-fill" id="pf-${g.id}" style="width:${pct}%;background:${g.accent};"></div></div>
              </div>
            </div>
            <div class="rw-panel">
              <div class="rw-title">🏆 RECENT WINNERS</div>
              <div id="rw-${g.id}"><div style="font-size:.65rem;color:#222;text-align:center;padding:4px;">No winners yet</div></div>
            </div>
          </div>
          <div class="buy-panel">
            <div class="bp-title">� BUY RAFFLE TICKETS</div>
            <div class="bp-row"><span class="bp-lbl">For Me</span><input class="bp-inp" type="number" min="1" max="10" value="1" id="qty-${g.id}" oninput="updCost('${g.id}',${g.price})"></div>
            <div class="bp-row"><span class="bp-lbl">Gift To</span><input class="bp-inp" type="text" placeholder="Friend's name or ID" id="gft-name-${g.id}"><input class="bp-inp" style="width:54px;flex:0 0 54px;" type="number" min="0" max="10" value="0" id="gft-${g.id}" oninput="updCost('${g.id}',${g.price})"></div>
            <div class="bp-cost" id="cost-${g.id}">Total: <span>${g.label}</span></div>
            <button class="bp-buy" style="background:${g.btnBg};color:${g.btnC};" onclick="openDDModal('${g.id}',${g.price},false)">💳 BUY TICKETS</button>
            <button class="bp-gift" onclick="openDDModal('${g.id}',${g.price},true)">🎁 GIFT TICKETS</button>
            <div class="bp-result" id="br-${g.id}"></div>
            <div class="my-tix"><div class="mx-ttl">YOUR TICKETS (Sequential 1–1,000,000)</div><div id="mt-${g.id}"><span style="font-size:.6rem;color:#1a1a1a;">Buy tickets to receive sequential numbers</span></div></div>
          </div>
        </div>
      </div>
    </div>
  </div>`;
}

document.getElementById('floorArea').innerHTML=G.map(buildMachine).join('');

/* ===== REEL SPIN — TRADITIONAL SYMBOLS ===== */
function doPull(gid){
  const gs=GS[gid];
  if(gs.spinning)return;
  const g=G.find(x=>x.id===gid);
  gs.spinning=true;gs.spins++;
  const btn=document.getElementById('pull-'+gid);
  btn.disabled=true;
  document.getElementById('pr-'+gid).innerHTML=`<span style="color:#555;">Spinning…</span>`;

  const syms=SYMBOLS_BY_TIER[gid];
  // Determine outcome first
  const finals=[];
  for(let i=0;i<g.reels;i++) finals.push(syms[Math.floor(Math.random()*syms.length)]);

  // 5% jackpot: all match
  if(Math.random()<0.05){const s=syms[Math.floor(Math.random()*syms.length)];finals.fill(s);}
  // 22% near-miss: all but last match
  else if(Math.random()<0.22){const s=syms[Math.floor(Math.random()*syms.length)];for(let i=0;i<g.reels-1;i++)finals[i]=s;}

  // Rebuild each strip with final symbol at position 12
  for(let i=0;i<g.reels;i++){
    const el=document.getElementById('rs-'+gid+'-'+i);
    let cells='';
    for(let j=0;j<30;j++){
      if(j===12) cells+=`<div class="reel-cell">${finals[i]}</div>`;
      else cells+=`<div class="reel-cell">${syms[Math.floor(Math.random()*syms.length)]}</div>`;
    }
    el.innerHTML=cells;
    el.style.transition='none';
    el.style.top='0px';
  }

  // Animate spin for each reel
  let done=0;
  for(let i=0;i<g.reels;i++){
    const duration=800+i*350;
    const el=document.getElementById('rs-'+gid+'-'+i);
    let pos=0;
    const speed=18+i*3;
    const iv=setInterval(()=>{pos-=speed;el.style.top=pos+'px';},16);
    setTimeout(()=>{
      clearInterval(iv);
      sndReelStop(i);
      // Snap to final position (cell 12 centered)
      el.style.transition='top .25s cubic-bezier(.15,.8,.25,1)';
      el.style.top=-(12*80)+'px';
      setTimeout(()=>{el.style.transition='none';},260);
      done++;
      if(done===g.reels) finishPull(gid,finals,g);
    },duration);
  }
}

function finishPull(gid,finals,g){
  const gs=GS[gid];
  gs.spinning=false;
  document.getElementById('pull-'+gid).disabled=false;
  const pr=document.getElementById('pr-'+gid);
  const allMatch=finals.every(v=>v===finals[0]);
  const nearMatch=finals.slice(0,-1).every(v=>v===finals[0])&&finals[finals.length-1]!==finals[0];
  // Count how many from the left match
  let matchRun=1;
  for(let i=1;i<finals.length;i++){if(finals[i]===finals[0])matchRun++;else break;}

  if(allMatch){
    /* ===== JACKPOT ===== */
    const sym=finals[0].repeat(g.reels);
    const payout='$'+g.total;
    pr.innerHTML=`<span style="color:#FFD700;font-size:1rem;font-weight:700;text-shadow:0 0 20px #FFD700,0 0 40px #FFD700;animation:pp 0.4s ease infinite;">� JACKPOT! ${sym}</span>`;
    sndJackpot();
    flashScreen('rgba(255,215,0,0.6)',300);
    setTimeout(()=>flashScreen('rgba(255,255,255,0.5)',120),350);
    setTimeout(()=>flashScreen('rgba(255,215,0,0.5)',200),600);
    spawnConfetti(220,['#FFD700','#FFA500','#fff','#ff1a44','#00ff66','#00ccff','#dd00ff']);
    sndCoin();
    setTimeout(()=>showWin('� JACKPOT! '+sym,' All '+g.reels+' reels matched on '+g.name+'! Prize: '+payout+' annuity. FREE ticket issued!'),500);
    apiBuyTicket(gid,1);
  } else if(nearMatch){
    /* ===== NEAR MISS ===== */
    const matchSym=finals[0];
    pr.innerHTML=`<span style="color:#ff9900;font-size:.88rem;text-shadow:0 0 8px #ff9900;">😱 SO CLOSE! ${matchSym.repeat(g.reels-1)} — one away from jackpot!</span>`;
    sndNear();
    flashScreen('rgba(255,100,0,0.3)',150);
    // Shake the last reel
    const lr=document.getElementById('reel-'+gid+'-'+(g.reels-1));
    let s=0;const sv=setInterval(()=>{if(lr)lr.style.transform=`translateX(${s%2?-5:5}px)`;s++;if(s>10){if(lr)lr.style.transform='';clearInterval(sv);}},45);
  } else if(matchRun>=2){
    /* ===== PARTIAL WIN ===== */
    const fakePrize=['$25','$50','$100','$250','$500'][Math.min(matchRun-2,4)];
    pr.innerHTML=`<span style="color:#00ff99;font-size:.85rem;text-shadow:0 0 6px #00ff99;">🎊 ${matchRun} in a row! Bonus: ${fakePrize} credit!</span>`;
    sndSmallWin();
    sndCoin();
    flashScreen('rgba(0,255,100,0.25)',200);
    spawnConfetti(60,['#00ff99','#FFD700','#fff','#00ccff']);
  } else {
    /* ===== NO WIN ===== */
    const msgs=['Keep spinning! Luck builds!','Almost there — try again!','The jackpot is warming up!','One more pull could change everything!','Fortune favors the bold!'];
    pr.innerHTML=`<span style="color:#333;font-size:.75rem;">${msgs[gs.spins%msgs.length]}</span>`;
  }
}

/* ===== API TICKET PURCHASE (REAL BACKEND) ===== */
async function apiBuyTicket(gid,qty,giftTo=''){
  try{
    const game=G.find(x=>x.id===gid);
    const gameId=gid==='025'?'0.25':gid; // Map frontend ID to backend game name
    const res=await fetch('/api/tickets/buy',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({game_id:gameId,owner_id:PLAYER_ID,qty:qty,gift_to:giftTo})
    });
    const data=await res.json();
    if(data.success){
      // Show real sequential ticket numbers
      data.tickets.forEach(t=>{
        GS[gid].myTickets.push(t);
      });
      renderMyTix(gid);
      // Update progress from server
      const pf=document.getElementById('pf-'+gid);
      const pc=document.getElementById('pct-'+gid);
      if(pf)pf.style.width=data.percent_sold.toFixed(1)+'%';
      if(pc)pc.textContent=data.percent_sold.toFixed(1)+'%';
    }
    return data;
  }catch(e){console.error('Ticket API error:',e);return null;}
}


/* ===== TICKET PURCHASE UI ===== */
function updCost(id,price){
  const q=Math.min(10,Math.max(0,parseInt(document.getElementById('qty-'+id).value)||0));
  const gf=Math.min(10,Math.max(0,parseInt(document.getElementById('gft-'+id).value)||0));
  document.getElementById('cost-'+id).innerHTML='Total: <span>$'+((q+gf)*price).toLocaleString('en-US',{minimumFractionDigits:2})+'</span>';
}
function showBR(id,msg,cls){
  const el=document.getElementById('br-'+id);el.className='bp-result show '+cls;el.textContent=msg;
  setTimeout(()=>el.className='bp-result',5500);
}
function renderMyTix(id){
  const el=document.getElementById('mt-'+id);
  const g=G.find(x=>x.id===id);
  const tix=GS[id].myTickets;
  if(!tix.length){el.innerHTML='<span style="font-size:.6rem;color:#1a1a1a;">Buy tickets to receive sequential numbers</span>';return;}
  el.innerHTML=tix.map(t=>`<span class="tkt" style="color:${g.accent};border-color:${g.accent}33;">#${t.formatted} <span style="font-size:.5rem;opacity:.4;">sig:${t.signature.substr(0,6)}</span></span>`).join('');
}
/* ===== DIRECT DEPOSIT MODAL LOGIC ===== */
let _ddGameId=null,_ddIsGift=false;
function openDDModal(id,price,isGift){
  // Validate qty first
  const q=Math.min(10,Math.max(1,parseInt(document.getElementById('qty-'+id).value)||1));
  const gf=Math.min(10,Math.max(0,parseInt(document.getElementById('gft-'+id).value)||0));
  if(isGift&&gf<1){showBR(id,'Set gift quantity > 0 first','');return;}
  if(!isGift&&q<1){showBR(id,'Set quantity > 0 first','');return;}
  _ddGameId=id; _ddIsGift=isGift;
  // Pre-fill from localStorage
  const saved=JSON.parse(localStorage.getItem('dd_info')||'{}');
  document.getElementById('dd-name').value=saved.name||'';
  document.getElementById('dd-email').value=saved.email||'';
  document.getElementById('dd-bank').value=saved.bank||'';
  document.getElementById('dd-acct-type').value=saved.acct_type||'checking';
  document.getElementById('dd-routing').value=saved.routing||'';
  document.getElementById('dd-account').value=saved.account||'';
  document.getElementById('dd-modal-sub').textContent=isGift
    ?'YOUR PAYOUT INFO — RECIPIENT CAN UPDATE WHEN CLAIMING'
    :'YOUR WINNING DEPOSIT INFORMATION';
  document.getElementById('dd-gift-notice').style.display=isGift?'block':'none';
  const confirmBtn=document.getElementById('dd-confirm-btn');
  confirmBtn.onclick=()=>confirmDDAndPurchase(id,price,isGift);
  document.getElementById('ddModal').classList.add('open');
}
function closeDDModal(){document.getElementById('ddModal').classList.remove('open');}
function saveDDInfo(){
  const info={
    name:document.getElementById('dd-name').value.trim(),
    email:document.getElementById('dd-email').value.trim(),
    bank:document.getElementById('dd-bank').value.trim(),
    acct_type:document.getElementById('dd-acct-type').value,
    routing:document.getElementById('dd-routing').value.trim(),
    account:document.getElementById('dd-account').value.trim()
  };
  localStorage.setItem('dd_info',JSON.stringify(info));
  return info;
}
async function confirmDDAndPurchase(id,price,isGift){
  const info=saveDDInfo();
  if(!info.name){alert('Please enter your full legal name.');return;}
  if(!info.routing||info.routing.length!==9){alert('Routing number must be exactly 9 digits.');return;}
  if(!info.account){alert('Please enter your account number.');return;}
  closeDDModal();
  if(isGift){
    const gf=Math.min(10,Math.max(1,parseInt(document.getElementById('gft-'+id).value)||1));
    const giftTo=document.getElementById('gft-name-'+id).value.trim()||'friend';
    sndCoin();
    const data=await apiBuyTicket(id,gf,giftTo);
    if(data&&data.success){
      showBR(id,`� ${gf} ticket${gf>1?'s':''} gifted to “${giftTo}” — #${data.tickets[0].formatted} — DD on file`,'gk');
      spawnConfetti(40,['#bb88ff','#FFD700','#fff']);
    } else showBR(id,'❌ Gift failed: '+(data?.error||'Error'),'');
  } else {
    const q=Math.min(10,Math.max(1,parseInt(document.getElementById('qty-'+id).value)||1));
    const gf=Math.min(10,Math.max(0,parseInt(document.getElementById('gft-'+id).value)||0));
    sndCoin();
    const data=await apiBuyTicket(id,q+gf);
    if(data&&data.success){
      let msg=`✅ ${q+gf} ticket${q+gf>1?'s':''} — #${data.tickets[0].formatted}`;
      if(data.tickets.length>1) msg+=` to #${data.tickets[data.tickets.length-1].formatted}`;
      msg+=` — DD on file`;
      showBR(id,msg,'ok');
      if(Math.random()<0.08){
        const wt=data.tickets[0].formatted;
        setTimeout(()=>showWin('🎉 INSTANT MATCH!','Ticket #'+wt+' matched! Payout will be sent to '+info.name+' at '+info.bank+' ('+info.acct_type+') ending in …'+info.account.slice(-4)+'. Monthly deposits start next cycle.'),800);
      }
    } else showBR(id,'❌ Purchase failed: '+(data?.error||'Error'),'');
  }
}

/* ===== PROGRESS BARS (polling API) ===== */
async function pollStatus(){
  try{
    const res=await fetch('/api/tickets/status');
    const data=await res.json();
    let totalTix=0,totalRev=0,totalDrawings=0;
    G.forEach(g=>{
      const gameId=g.id==='025'?'0.25':g.id;
      const s=data[gameId];
      if(!s)return;
      const pct=s.percent_sold;
      const pf=document.getElementById('pf-'+g.id);
      const pc=document.getElementById('pct-'+g.id);
      const ptl=document.getElementById('ptl-'+g.id);
      if(pf)pf.style.width=pct.toFixed(4)+'%';
      if(pc)pc.textContent=pct.toFixed(4)+'%';
      if(ptl)ptl.textContent='Tickets: '+s.tickets_sold.toLocaleString()+' / 1,000,000';
      totalTix+=s.tickets_sold;
      totalRev+=s.total_revenue;
      totalDrawings+=s.past_drawings;
    });
    document.getElementById('lv-tickets').textContent=totalTix.toLocaleString();
    document.getElementById('lv-revenue').textContent='$'+totalRev.toLocaleString('en-US',{minimumFractionDigits:2});
    document.getElementById('lv-drawings').textContent=totalDrawings.toString();
  }catch(e){}
}
setInterval(pollStatus,3000);
pollStatus();

/* Progress driven solely by real API data from pollStatus() */

/* ===== CHARTS ===== */
let chartsBuilt=false;
function toggleCharts(){const b=document.getElementById('chartsBody');b.classList.toggle('open');if(b.classList.contains('open')&&!chartsBuilt){buildCharts();chartsBuilt=true;}}
const labels=SIM.map(d=>'M'+d.month);
let tierChart=null;
function mkC(id,type,ds){return new Chart(document.getElementById(id).getContext('2d'),{type,data:{labels,datasets:ds},options:{responsive:true,animation:{duration:200},plugins:{legend:{labels:{color:'#444',font:{size:9}}}},scales:type!='doughnut'?{x:{ticks:{color:'#333',maxTicksLimit:10},grid:{color:'rgba(255,255,255,.02)'}},y:{ticks:{color:'#333'},grid:{color:'rgba(255,255,255,.02)'}}}:{}}});}
function buildCharts(){
  mkC('revChart','line',[{label:'Revenue',data:SIM.map(d=>d.monthly_revenue),borderColor:'#FFD700',backgroundColor:'rgba(255,215,0,.05)',fill:true,tension:.4,pointRadius:0},{label:'Payouts',data:SIM.map(d=>d.monthly_payouts),borderColor:'#00ff66',backgroundColor:'rgba(0,255,80,.04)',fill:true,tension:.4,pointRadius:0}]);
  mkC('recipChart','line',[{label:'Recipients',data:SIM.map(d=>d.active_recipients_total),borderColor:'#cc44ff',backgroundColor:'rgba(180,0,255,.05)',fill:true,tension:.4,pointRadius:0}]);
  mkC('cumChart','line',[{label:'Revenue',data:SIM.map(d=>d.cumulative_revenue),borderColor:'#FFD700',backgroundColor:'rgba(255,215,0,.04)',fill:true,tension:.4,pointRadius:0},{label:'Payouts',data:SIM.map(d=>d.cumulative_payouts),borderColor:'#ff1a44',backgroundColor:'rgba(255,0,40,.03)',fill:true,tension:.4,pointRadius:0}]);
  tierChart=new Chart(document.getElementById('tierPieChart').getContext('2d'),{type:'doughnut',data:{labels:GAMES_DATA.map(g=>'$'+g.name),datasets:[{data:GAMES_DATA.map(()=>0),backgroundColor:TC,borderWidth:2}]},options:{responsive:true,plugins:{legend:{labels:{color:'#555'}}}}});
  updateDash(SIM.length-1);
}
function fmt(n){return n>=1e12?'$'+(n/1e12).toFixed(2)+'T':n>=1e9?'$'+(n/1e9).toFixed(2)+'B':n>=1e6?'$'+(n/1e6).toFixed(1)+'M':'$'+n.toLocaleString();}
function fmtN(n){return n>=1e9?(n/1e9).toFixed(2)+'B':n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(0)+'K':n.toLocaleString();}
function updateDash(idx){
  const d=SIM[idx];document.getElementById('monthLabel').textContent='Month '+d.month;
  document.getElementById('statsGrid').innerHTML=`<div class="sc-s"><div class="sl">Players</div><div class="sv bl">${fmtN(d.players)}</div></div><div class="sc-s"><div class="sl">Revenue</div><div class="sv go">${fmt(d.monthly_revenue)}</div></div><div class="sc-s"><div class="sl">Payouts</div><div class="sv gr">${fmt(d.monthly_payouts)}</div></div><div class="sc-s"><div class="sl">Taxes</div><div class="sv rd">${fmt(d.taxes_collected)}</div></div><div class="sc-s"><div class="sl">Net</div><div class="sv go">${fmt(d.net_to_winners)}</div></div><div class="sc-s"><div class="sl">Recipients</div><div class="sv pu">${fmtN(d.active_recipients_total)}</div></div>`;
  document.getElementById('jackpotStrip').innerHTML=`<div class="jp">Revenue: <span>${fmt(d.cumulative_revenue)}</span></div><div class="jp">Payouts: <span>${fmt(d.cumulative_payouts)}</span></div>`;
  if(tierChart){tierChart.data.datasets[0].data=GAMES_DATA.map(g=>d[g.name+'_revenue']||0);tierChart.update();}
}
document.getElementById('monthSlider').addEventListener('input',function(){updateDash(parseInt(this.value)-1);});
</script>
</body>
</html>
"""


# ====================== FLASK APP ======================
app = Flask(__name__)
_sim_results: List[Dict] = []
_sim_months: int = DEFAULT_MONTHS


@app.route("/")
def index():
    games_data = [{"name": g.name, "price": g.price, "monthly_payout": g.monthly_payout,
                   "payout_months": g.payout_months} for g in GAMES]
    return render_template_string(
        DASHBOARD_HTML,
        sim_data=_sim_results,
        games_data=games_data,
        months=_sim_months
    )


@app.route("/api/data")
def api_data():
    return jsonify(_sim_results)


@app.route("/api/tickets/buy", methods=["POST"])
def api_buy_tickets():
    """Purchase tickets via the registry. Requires game_id, owner_id, qty."""
    data = request.get_json(force=True)
    game_id = data.get("game_id", "")
    owner_id = data.get("owner_id", "")
    qty = int(data.get("qty", 1))
    gift_to = data.get("gift_to", "")

    if not owner_id:
        owner_id = f"anon_{secrets.token_hex(8)}"

    try:
        result = ticket_registry.purchase_tickets(game_id, owner_id, qty, gift_to)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/tickets/status")
def api_tickets_status():
    """Get current ticket pool status for all games."""
    return jsonify(ticket_registry.get_all_status())


@app.route("/api/tickets/status/<game_id>")
def api_game_status(game_id):
    """Get status for a specific game."""
    try:
        return jsonify(ticket_registry.get_game_status(game_id))
    except KeyError:
        return jsonify({"error": "Invalid game"}), 404


@app.route("/api/tickets/verify", methods=["POST"])
def api_verify_ticket():
    """Verify a ticket's authenticity via HMAC signature."""
    data = request.get_json(force=True)
    ticket = Ticket(
        ticket_id=int(data["ticket_id"]),
        game_id=data["game_id"],
        drawing_id=int(data["drawing_id"]),
        owner_id=data["owner_id"],
        purchased_at=0,
        signature=data["signature"],
    )
    valid = ticket_registry.verify_ticket(ticket)
    return jsonify({"valid": valid, "ticket_id": ticket.ticket_id})


@app.route("/api/tickets/winners/<game_id>")
def api_recent_winners(game_id):
    """Get recent winners for a game."""
    winners = ticket_registry.get_recent_winners(game_id)
    return jsonify({"game_id": game_id, "winners": winners})


def main():
    global _sim_results, _sim_months

    parser = argparse.ArgumentParser(description="Generation 11 Full-Tier Global Raffle Simulator")
    parser.add_argument("--months", type=int, default=DEFAULT_MONTHS)
    parser.add_argument("--players-final", type=int, default=DEFAULT_FINAL_PLAYERS)
    parser.add_argument("--intensity", type=float, default=DEFAULT_BASE_INTENSITY)
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    _sim_months = args.months
    sim = GlobalRaffleSimulator(
        months=args.months,
        final_players=args.players_final,
        base_intensity=args.intensity
    )
    _sim_results = sim.run()

    url = f"http://localhost:{args.port}"
    print(f"\n🎰 Casino Dashboard running at: {url}")
    print("   Press Ctrl+C to stop.\n")

    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="0.0.0.0", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()