#!/usr/bin/env python3
"""
Raffle Monolith v11.0 - Generation 11 Full Multi-Tier Global System
====================================================================
Flask web dashboard edition: runs the simulation then serves a
casino-themed browser dashboard at http://localhost:5000
"""

import argparse
import csv
import json
import multiprocessing as mp
import threading
import webbrowser
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from flask import Flask, jsonify, render_template_string


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
<title>🎰 Gman's Casino MaxPlus Pro v1.17</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@700;900&family=Rajdhani:wght@400;600&family=Oswald:wght@400;700&family=Bebas+Neue&display=swap');
  :root{
    --gold:#FFD700;--gold2:#FFA500;--gold3:#B8860B;
    --nr:#ff1a44;--nb:#00ddff;--ng:#00ff55;--np:#ee00ff;--ngold:#ffee33;
    --felt:#0b3d1a;--felt2:#071a0c;
    --dark:#020204;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  ::-webkit-scrollbar{width:5px;background:#020204;}
  ::-webkit-scrollbar-thumb{background:var(--gold3);border-radius:3px;}
  body{
    background:var(--dark);color:#e8e0c8;font-family:'Rajdhani',sans-serif;
    min-height:100vh;overflow-x:hidden;
    background-image:radial-gradient(ellipse at 50% 0%,rgba(50,0,90,.9) 0%,transparent 55%);
  }
  #bgCanvas{position:fixed;inset:0;pointer-events:none;z-index:0;}
  #confCanvas{position:fixed;inset:0;z-index:9997;pointer-events:none;display:none;}
  #confCanvas.show{display:block;}

  /* MARQUEE */
  .mbar{position:relative;z-index:10;background:linear-gradient(90deg,#1a0004,#380010,#1a0004);
    border-bottom:3px solid var(--nr);box-shadow:0 0 30px var(--nr),0 0 80px rgba(255,0,40,.25);
    padding:7px 0;overflow:hidden;white-space:nowrap;}
  .minner{display:inline-block;animation:mar 34s linear infinite;
    font-family:'Oswald',sans-serif;font-size:.95rem;letter-spacing:5px;color:var(--ngold);
    text-shadow:0 0 12px var(--gold),0 0 30px var(--gold2);}
  @keyframes mar{from{transform:translateX(100vw)}to{transform:translateX(-100%)}}

  /* HEADER */
  #mainSign{position:relative;z-index:10;text-align:center;padding:22px 20px 16px;
    background:linear-gradient(180deg,#14002a 0%,#0c0018 60%,transparent 100%);
    border-bottom:1px solid rgba(255,215,0,.1);}
  .sign-frame{display:inline-block;background:linear-gradient(180deg,#200040,#100020);
    border:4px solid var(--gold3);border-radius:12px;padding:16px 44px 14px;
    box-shadow:0 0 0 2px rgba(255,215,0,.14),0 0 40px rgba(255,80,0,.45),0 0 100px rgba(180,0,80,.18),inset 0 0 50px rgba(90,0,30,.5);}
  .sign-frame h1{font-family:'Cinzel',serif;font-size:clamp(2rem,5vw,3.8rem);
    background:linear-gradient(180deg,#fffbe0,#FFD700 38%,#FFA500 68%,#aa5500);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:5px;line-height:1.05;
    filter:drop-shadow(0 0 12px rgba(255,200,0,.65));}
  .sign-sub{font-family:'Oswald',sans-serif;color:rgba(255,215,0,.55);font-size:.82rem;letter-spacing:4px;margin-top:4px;}
  .bulbs{display:flex;justify-content:center;gap:7px;margin-top:8px;}
  .blb{width:11px;height:11px;border-radius:50%;animation:bc 1.1s infinite;box-shadow:0 0 6px currentColor;}
  .blb.r{color:var(--nr);background:var(--nr);}
  .blb.g{color:var(--ng);background:var(--ng);}
  .blb.b{color:var(--nb);background:var(--nb);}
  .blb.y{color:var(--ngold);background:var(--ngold);}
  .blb.p{color:var(--np);background:var(--np);}
  @keyframes bc{0%,49%{opacity:1}50%,100%{opacity:.1}}
  .vpill{display:inline-block;margin-top:10px;background:rgba(255,215,0,.08);
    border:1px solid rgba(255,215,0,.32);border-radius:20px;padding:3px 14px;
    font-size:.75rem;color:var(--gold);letter-spacing:3px;font-family:'Cinzel',serif;}

  /* NEON DIVIDER */
  .ndiv{height:4px;position:relative;z-index:10;
    background:linear-gradient(90deg,var(--nr),var(--ngold),var(--ng),var(--nb),var(--np),var(--nr));
    background-size:300% 100%;animation:rs 3s linear infinite;
    box-shadow:0 0 20px rgba(255,200,0,.5),0 0 40px rgba(255,100,0,.25);}
  @keyframes rs{from{background-position:0%}to{background-position:300%}}

  /* LIVE STATS */
  .live-bar{position:relative;z-index:10;padding:16px 20px 12px;
    background:linear-gradient(135deg,rgba(0,255,80,.03),transparent);}
  .live-title{font-family:'Cinzel',serif;font-size:.9rem;color:var(--ng);letter-spacing:3px;
    text-align:center;margin-bottom:10px;animation:gp 2s ease infinite;
    text-shadow:0 0 14px var(--ng),0 0 30px rgba(0,255,80,.4);}
  @keyframes gp{0%,100%{text-shadow:0 0 14px var(--ng),0 0 30px rgba(0,255,80,.4)}50%{text-shadow:0 0 28px var(--ng),0 0 60px rgba(0,255,80,.7)}}
  .lbadge{display:inline-block;background:var(--nr);color:#fff;font-size:.6rem;letter-spacing:2px;
    padding:2px 7px;border-radius:3px;vertical-align:middle;margin-left:6px;
    animation:bl 0.8s infinite;font-weight:900;font-family:'Oswald',sans-serif;box-shadow:0 0 8px var(--nr);}
  @keyframes bl{0%,100%{opacity:1;box-shadow:0 0 8px var(--nr)}50%{opacity:.15;box-shadow:none}}
  .zg{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;}
  .zc{background:linear-gradient(135deg,#071209,#040a06);border:1px solid rgba(0,255,80,.18);
    border-radius:8px;padding:10px;text-align:center;}
  .zc .zl{font-size:.62rem;letter-spacing:2px;color:#1a4428;text-transform:uppercase;margin-bottom:2px;}
  .zc .zv{font-size:1.25rem;font-weight:700;color:var(--ng);font-family:'Oswald',sans-serif;
    text-shadow:0 0 10px rgba(0,255,80,.55);}
  .pln{text-align:center;color:#1a3020;font-size:.7rem;margin-top:6px;letter-spacing:1px;}

  /* TICKER */
  .ticker-wrap{position:relative;z-index:10;background:rgba(0,0,0,.7);
    border-top:1px solid rgba(255,215,0,.12);border-bottom:1px solid rgba(255,215,0,.12);
    padding:7px 0;overflow:hidden;white-space:nowrap;}
  .ticker-inner{display:inline-block;animation:tick 28s linear infinite;
    font-family:'Oswald',sans-serif;font-size:.82rem;letter-spacing:3px;}
  @keyframes tick{from{transform:translateX(100vw)}to{transform:translateX(-100%)}}

  /* ======= RAFFLE FLOOR ======= */
  .raffle-floor{position:relative;z-index:10;padding:24px 16px;}
  .floor-title{font-family:'Cinzel',serif;font-size:1.5rem;color:var(--gold);letter-spacing:5px;
    text-align:center;margin-bottom:26px;
    text-shadow:0 0 20px rgba(255,200,0,.55),0 0 50px rgba(255,100,0,.28);
    animation:flick 5s ease infinite;}
  @keyframes flick{0%,90%,96%,100%{opacity:1}91%,95%{opacity:.6}93%{opacity:.2}}
  .floor-title span{color:var(--nr);text-shadow:0 0 18px var(--nr);}
  .games-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:22px;}

  /* ======= RAFFLE GAME CARD ======= */
  .rgame{position:relative;border-radius:18px;overflow:hidden;border:3px solid;
    box-shadow:0 0 0 1px rgba(0,0,0,.8),0 14px 55px rgba(0,0,0,.8);
    transition:transform .18s,box-shadow .18s;}
  .rgame:hover{transform:translateY(-4px);box-shadow:0 0 0 1px rgba(0,0,0,.8),0 20px 70px rgba(0,0,0,.8),0 0 40px rgba(255,215,0,.08);}

  /* cabinet header */
  .rg-head{padding:12px 18px 10px;text-align:center;border-bottom:2px solid rgba(255,255,255,.07);position:relative;}
  .rg-head::before{content:'';position:absolute;inset:0;
    background:repeating-linear-gradient(90deg,transparent,transparent 18px,rgba(255,255,255,.012) 18px,rgba(255,255,255,.012) 19px);}
  .rg-game-name{font-family:'Cinzel',serif;font-size:1rem;letter-spacing:3px;
    text-shadow:0 0 10px currentColor;position:relative;z-index:1;}
  .rg-price{font-family:'Oswald',sans-serif;font-size:2rem;font-weight:700;
    text-shadow:0 0 18px currentColor;position:relative;z-index:1;
    animation:pp 1.8s ease infinite;}
  @keyframes pp{0%,100%{filter:brightness(1)}50%{filter:brightness(1.5)}}
  .rg-pool{font-family:'Cinzel',serif;font-size:.78rem;letter-spacing:2px;
    color:rgba(255,255,255,.5);position:relative;z-index:1;margin-top:2px;}

  /* bulb strip */
  .rg-bulbs{display:flex;gap:4px;padding:5px 14px;background:rgba(0,0,0,.35);
    flex-wrap:wrap;justify-content:center;}
  .rb{width:8px;height:8px;border-radius:50%;animation:rb 1s infinite;box-shadow:0 0 4px currentColor;}
  @keyframes rb{0%,49%{opacity:1}50%,100%{opacity:.08}}

  /* felt body */
  .rg-body{background:radial-gradient(ellipse at 50% 30%,var(--felt) 0%,var(--felt2) 100%);
    padding:16px 18px;position:relative;}
  .rg-body::before{content:'';position:absolute;inset:0;pointer-events:none;
    background:repeating-linear-gradient(0deg,transparent,transparent 28px,rgba(0,0,0,.07) 28px,rgba(0,0,0,.07) 29px),
      repeating-linear-gradient(90deg,transparent,transparent 28px,rgba(0,0,0,.07) 28px,rgba(0,0,0,.07) 29px);}

  /* ---- BALL MACHINE ---- */
  .ball-machine{position:relative;z-index:1;margin-bottom:14px;}
  .bm-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;}
  .bm-label{font-family:'Cinzel',serif;font-size:.72rem;letter-spacing:2px;color:rgba(255,255,255,.4);}
  .bm-status{font-family:'Oswald',sans-serif;font-size:.78rem;letter-spacing:2px;
    padding:2px 10px;border-radius:3px;font-weight:700;}
  .bm-status.open{background:rgba(0,255,80,.15);border:1px solid rgba(0,255,80,.3);color:var(--ng);}
  .bm-status.drawing{background:rgba(255,200,0,.15);border:1px solid rgba(255,200,0,.4);color:var(--gold);animation:bl 0.6s infinite;}
  /* lottery ball display */
  .balls-display{display:flex;gap:6px;flex-wrap:wrap;min-height:44px;align-items:center;
    background:rgba(0,0,0,.4);border-radius:8px;padding:8px 10px;
    border:1px solid rgba(255,255,255,.06);}
  .ball{
    width:36px;height:36px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;
    font-family:'Oswald',sans-serif;font-size:.85rem;font-weight:700;
    box-shadow:inset -3px -3px 6px rgba(0,0,0,.4),inset 2px 2px 5px rgba(255,255,255,.2),0 3px 10px rgba(0,0,0,.5);
    animation:ball-drop .4s cubic-bezier(.18,1.4,.4,1);
    position:relative;overflow:hidden;
    flex-shrink:0;
  }
  .ball::before{content:'';position:absolute;top:3px;left:6px;width:10px;height:6px;
    border-radius:50%;background:rgba(255,255,255,.3);}
  @keyframes ball-drop{from{transform:scale(0) translateY(-20px);opacity:0}to{transform:scale(1) translateY(0);opacity:1}}
  .ball.my{border:2px solid rgba(255,255,255,.5);}
  .ball-placeholder{color:rgba(255,255,255,.15);font-size:.75rem;letter-spacing:2px;font-family:'Oswald',sans-serif;}

  /* ticket counter progress */
  .tix-progress{margin-bottom:12px;position:relative;z-index:1;}
  .tix-progress-top{display:flex;justify-content:space-between;font-size:.7rem;
    color:rgba(255,255,255,.35);letter-spacing:1px;margin-bottom:4px;}
  .tix-progress-top .hot{animation:bl 0.9s infinite;}
  .prog-bg{height:8px;background:rgba(0,0,0,.5);border-radius:4px;overflow:hidden;
    border:1px solid rgba(255,255,255,.06);}
  .prog-fill{height:100%;border-radius:4px;transition:width .5s ease;
    animation:pg 2s ease infinite;}
  @keyframes pg{0%,100%{filter:brightness(1)}50%{filter:brightness(1.6)box-shadow:0 0 8px currentColor}}

  /* game stats */
  .rg-stats{position:relative;z-index:1;margin-bottom:12px;}
  .rs-row{display:flex;justify-content:space-between;align-items:center;
    padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:.88rem;}
  .rs-row:last-child{border-bottom:none;}
  .rs-l{color:rgba(255,255,255,.38);font-size:.78rem;letter-spacing:1px;}
  .rs-v{font-weight:700;color:#f0e8cc;}
  .rs-v.hl{color:var(--gold);text-shadow:0 0 5px rgba(255,200,0,.35);}

  /* ---- BUY PANEL ---- */
  .buy-panel{position:relative;z-index:1;background:rgba(0,0,0,.35);
    border:1px solid rgba(255,215,0,.12);border-radius:11px;padding:14px;}
  .bp-title{font-family:'Cinzel',serif;font-size:.82rem;color:var(--gold);
    letter-spacing:2px;margin-bottom:10px;text-align:center;}
  .bp-row{display:flex;align-items:center;gap:8px;margin-bottom:8px;}
  .bp-lbl{font-size:.72rem;letter-spacing:1px;color:rgba(255,255,255,.4);min-width:52px;}
  .bp-qty{flex:1;background:rgba(0,0,0,.6);border:1px solid rgba(255,215,0,.22);border-radius:5px;
    color:var(--gold);font-size:.95rem;font-family:'Oswald',sans-serif;padding:5px 8px;
    outline:none;text-align:center;}
  .bp-qty:focus{border-color:var(--gold);box-shadow:0 0 7px rgba(255,200,0,.28);}
  .bp-cost{text-align:center;font-size:.78rem;color:rgba(255,255,255,.32);margin-bottom:8px;}
  .bp-cost span{color:var(--gold);font-weight:700;}
  .btn-buy{width:100%;padding:11px;border:none;border-radius:8px;cursor:pointer;
    font-family:'Cinzel',serif;font-size:.92rem;font-weight:700;letter-spacing:2px;
    transition:all .12s;position:relative;overflow:hidden;}
  .btn-buy::after{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,255,255,.12),transparent);}
  .btn-buy:hover{filter:brightness(1.22);transform:translateY(-1px);}
  .btn-buy:active{transform:translateY(1px);filter:brightness(.88);}
  .btn-gift{width:100%;padding:7px;margin-top:6px;border-radius:7px;cursor:pointer;
    background:linear-gradient(135deg,#150040,#3800aa,#150040);
    border:1px solid rgba(130,40,255,.38);
    font-family:'Cinzel',serif;font-size:.78rem;font-weight:700;color:#bb88ff;letter-spacing:2px;
    transition:all .12s;}
  .btn-gift:hover{filter:brightness(1.2);box-shadow:0 0 14px rgba(120,0,255,.38);}
  .bp-result{margin-top:8px;padding:8px 10px;border-radius:7px;font-size:.8rem;
    text-align:center;display:none;font-family:'Oswald',sans-serif;letter-spacing:1px;}
  .bp-result.show{display:block;}
  .bp-result.ok{background:rgba(0,150,50,.14);border:1px solid rgba(0,255,80,.24);color:#00ff88;}
  .bp-result.gk{background:rgba(100,0,180,.14);border:1px solid rgba(160,40,255,.24);color:#bb88ff;}

  /* TICKET STUBS */
  .ticket-stubs{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px;justify-content:center;min-height:22px;}
  .tstub{
    display:inline-flex;align-items:center;gap:4px;
    background:linear-gradient(135deg,rgba(255,215,0,.12),rgba(255,170,0,.06));
    border:1px solid rgba(255,215,0,.3);border-radius:4px;
    padding:3px 7px;font-size:.68rem;color:var(--gold);font-family:'Oswald',sans-serif;
    letter-spacing:1px;animation:tpop .25s ease;
  }
  @keyframes tpop{from{transform:scale(0);opacity:0}80%{transform:scale(1.1)}to{transform:scale(1);opacity:1}}
  .tstub.gift{color:#bb88ff;background:rgba(140,0,255,.1);border-color:rgba(160,40,255,.28);}
  .tstub .tnum{font-weight:700;font-size:.72rem;}

  /* ======= DRAWING HISTORY ======= */
  .draw-history{position:relative;z-index:10;padding:0 16px 24px;}
  .dh-title{font-family:'Cinzel',serif;font-size:1.1rem;color:var(--gold);letter-spacing:3px;
    text-align:center;margin-bottom:14px;text-shadow:0 0 12px rgba(255,200,0,.35);}
  .dh-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;}
  .dh-card{background:linear-gradient(135deg,#0a0c10,#06080c);
    border:1px solid rgba(255,215,0,.08);border-radius:10px;padding:14px;}
  .dh-card-title{font-family:'Cinzel',serif;font-size:.82rem;letter-spacing:2px;margin-bottom:10px;}
  .dh-winner{display:flex;align-items:center;gap:8px;padding:5px 0;
    border-bottom:1px solid rgba(255,255,255,.04);font-size:.82rem;}
  .dh-winner:last-child{border-bottom:none;}
  .dh-tk{font-family:'Oswald',sans-serif;color:rgba(255,215,0,.7);letter-spacing:1px;}
  .dh-prize{margin-left:auto;color:var(--ng);font-weight:700;font-family:'Oswald',sans-serif;}
  .dh-num{
    width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;
    font-family:'Oswald',sans-serif;font-size:.72rem;font-weight:700;flex-shrink:0;
    box-shadow:inset -2px -2px 4px rgba(0,0,0,.4),inset 1px 1px 3px rgba(255,255,255,.2);
  }

  /* ======= SCRATCH ======= */
  .scratch-section{position:relative;z-index:10;padding:0 16px 26px;}
  .scratch-title{font-family:'Cinzel',serif;font-size:1.1rem;color:var(--gold);
    letter-spacing:4px;text-align:center;margin-bottom:14px;
    text-shadow:0 0 12px rgba(255,200,0,.38);}
  .scratch-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;}
  .sc-card{position:relative;height:105px;border-radius:10px;overflow:hidden;
    cursor:pointer;box-shadow:0 6px 22px rgba(0,0,0,.7);transition:transform .14s;}
  .sc-card:hover{transform:translateY(-3px) scale(1.02);}
  .sc-bg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px;}
  .sc-prize{font-family:'Oswald',sans-serif;font-size:1.2rem;font-weight:700;color:var(--gold);}
  .sc-sub{font-size:.65rem;letter-spacing:2px;color:rgba(255,255,255,.42);text-transform:uppercase;}
  .sc-foil{position:absolute;inset:0;border-radius:10px;z-index:2;
    display:flex;align-items:center;justify-content:center;flex-direction:column;gap:3px;
    background:linear-gradient(115deg,#666 0%,#ccc 20%,#888 40%,#ddd 55%,#777 75%,#bbb 100%);
    background-size:200% 200%;animation:fs 2.5s ease infinite;
    font-family:'Cinzel',serif;font-size:.8rem;color:#333;letter-spacing:2px;
    transition:opacity .5s ease,transform .5s ease;cursor:pointer;}
  @keyframes fs{0%{background-position:200% 0%}100%{background-position:-200% 0%}}
  .sc-foil.scratched{opacity:0;transform:scale(1.06);pointer-events:none;}

  /* ======= WIN POPUP ======= */
  #winOverlay{position:fixed;inset:0;z-index:9998;pointer-events:none;display:none;}
  #winOverlay.show{display:block;}
  #winPopup{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) scale(0);
    z-index:9999;pointer-events:all;
    background:linear-gradient(135deg,#1c0035,#2c0050);
    border:3px solid var(--gold);border-radius:18px;padding:28px 44px;text-align:center;
    box-shadow:0 0 80px rgba(255,200,0,.55),0 0 160px rgba(200,0,255,.28);
    transition:transform .35s cubic-bezier(.18,1.4,.4,1);}
  #winOverlay.show #winPopup{transform:translate(-50%,-50%) scale(1);}
  #winPopup h2{font-family:'Cinzel',serif;font-size:2.2rem;
    background:linear-gradient(135deg,#fffbe0,#FFD700,#FFA500);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    margin-bottom:8px;filter:drop-shadow(0 0 10px rgba(255,200,0,.65));}
  #winPopup p{font-family:'Oswald',sans-serif;font-size:1.05rem;color:#ddd;letter-spacing:2px;line-height:1.6;}
  #winPopup .wclose{margin-top:14px;background:linear-gradient(135deg,#aa7000,#FFD700,#aa7000);
    color:#1a0800;border:none;border-radius:8px;padding:9px 26px;
    cursor:pointer;font-family:'Cinzel',serif;font-size:.9rem;letter-spacing:2px;font-weight:700;}

  /* CHARTS TOGGLE */
  .charts-toggle{display:block;width:100%;padding:12px;position:relative;z-index:10;
    background:rgba(255,215,0,.04);border:none;
    border-top:1px solid rgba(255,215,0,.08);border-bottom:1px solid rgba(255,215,0,.08);
    color:rgba(255,215,0,.38);font-family:'Cinzel',serif;font-size:.8rem;letter-spacing:2px;
    cursor:pointer;text-align:center;}
  .charts-toggle:hover{background:rgba(255,215,0,.09);color:rgba(255,215,0,.7);}
  .charts-body{display:none;padding:16px;position:relative;z-index:10;}
  .charts-body.open{display:block;}
  .cr{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px;}
  @media(max-width:760px){.cr{grid-template-columns:1fr;}}
  .cc{background:linear-gradient(135deg,#0a1218,#070d14);border:1px solid rgba(255,215,0,.07);border-radius:10px;padding:14px;}
  .cc h3{font-family:'Cinzel',serif;font-size:.78rem;color:rgba(255,215,0,.4);letter-spacing:2px;margin-bottom:10px;text-transform:uppercase;}
  .proj-note{text-align:center;color:rgba(255,215,0,.24);font-size:.68rem;padding:0 0 10px;letter-spacing:1px;}
  .sslider{padding:0 0 14px;}
  .sslider-t{font-family:'Cinzel',serif;font-size:.8rem;color:rgba(255,215,0,.34);letter-spacing:2px;text-align:center;margin-bottom:8px;}
  .sw{display:flex;align-items:center;gap:10px;}
  #monthSlider{flex:1;-webkit-appearance:none;height:5px;background:linear-gradient(90deg,var(--ng),var(--gold),var(--nr));border-radius:3px;outline:none;cursor:pointer;}
  #monthSlider::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:radial-gradient(circle,var(--gold),var(--gold2));box-shadow:0 0 10px var(--gold);cursor:pointer;}
  #monthLabel{color:var(--gold);font-size:.85rem;font-weight:700;min-width:70px;text-align:right;font-family:'Oswald',sans-serif;}
  .sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px;margin-bottom:14px;}
  .sc-stat{background:linear-gradient(135deg,#0a1218,#070d14);border:1px solid rgba(255,215,0,.07);border-radius:8px;padding:12px 8px;text-align:center;}
  .sc-stat .sl{font-size:.6rem;letter-spacing:2px;color:#334;text-transform:uppercase;margin-bottom:3px;}
  .sc-stat .sv{font-size:1.25rem;font-weight:700;font-family:'Oswald',sans-serif;}
  .sv.go{color:var(--gold)}.sv.gr{color:var(--ng)}.sv.bl{color:var(--nb)}.sv.rd{color:var(--nr)}.sv.pu{color:var(--np)}
  .jp-strip{display:flex;justify-content:center;gap:12px;flex-wrap:wrap;margin-bottom:12px;}
  .jp{background:linear-gradient(135deg,#180028,#240040);border:1px solid rgba(255,215,0,.24);border-radius:22px;padding:6px 14px;font-size:.78rem;letter-spacing:1px;}
  .jp span{color:var(--gold);font-weight:700;font-family:'Oswald',sans-serif;}

  /* ABOUT */
  .about-sec{padding:24px 16px;position:relative;z-index:10;}
  .about-t{font-family:'Cinzel',serif;font-size:1.1rem;color:var(--gold);letter-spacing:3px;text-align:center;margin-bottom:16px;text-shadow:0 0 10px rgba(255,200,0,.25);}
  .ag{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;}
  .ac{background:linear-gradient(135deg,#0a1218,#070d14);border:1px solid rgba(255,215,0,.06);border-radius:10px;padding:16px;}
  .ac h3{font-family:'Cinzel',serif;font-size:.88rem;margin-bottom:8px;letter-spacing:1px;}
  .ac p,.ac li{font-size:.85rem;color:#6a7a8a;line-height:1.7;}
  .ac ul{padding-left:14px;}.ac li{margin-bottom:3px;}.ac li span{color:var(--gold);font-weight:700;}

  .sgap{height:20px;}
  footer{text-align:center;padding:14px;color:#1a1a1a;font-size:.72rem;border-top:1px solid rgba(255,215,0,.04);position:relative;z-index:10;}
</style>
</head>
<body>

<canvas id="bgCanvas"></canvas>
<canvas id="confCanvas"></canvas>

<!-- WIN OVERLAY -->
<div id="winOverlay">
  <div id="winPopup">
    <h2 id="winTitle">🎉 WINNER!</h2>
    <p id="winMsg">You won!</p>
    <button class="wclose" onclick="closeWin()">🎰 COLLECT &amp; PLAY AGAIN</button>
  </div>
</div>

<!-- MARQUEE -->
<div class="mbar"><span class="minner">
  🎰 GMAN'S CASINO MAXPLUS PRO v1.17 &nbsp;★&nbsp; 5 RAFFLE GAMES · BUY UP TO 10 TICKETS PER GAME &nbsp;★&nbsp; GIFT TICKETS TO FRIENDS &nbsp;★&nbsp; 1,000,000 TICKETS SOLD = DRAWING FIRES &nbsp;★&nbsp; MONTHLY ANNUITY PAYMENTS TO WINNERS &nbsp;★&nbsp; 25% TAX AUTO-WITHHELD &nbsp;★&nbsp; PLAY RESPONSIBLY &nbsp;★&nbsp;
</span></div>

<!-- MAIN SIGN -->
<div id="mainSign">
  <div class="sign-frame">
    <div class="bulbs" id="topBulbs"></div>
    <h1>🎰 Gman's Casino<br>MaxPlus Pro</h1>
    <div class="sign-sub">GLOBAL MULTI-TIER RAFFLE · GENERATION 11 ARCHITECTURE</div>
    <div class="bulbs" id="botBulbs"></div>
  </div>
  <div style="margin-top:10px;"><div class="vpill">v1.17 — RAFFLE CASINO · PRE-LAUNCH</div></div>
</div>
<div class="ndiv"></div>

<!-- LIVE STATS -->
<div class="live-bar">
  <div class="live-title">📡 LIVE SYSTEM STATS <span class="lbadge">LIVE</span></div>
  <div class="zg">
    <div class="zc"><div class="zl">Users</div><div class="zv">0</div></div>
    <div class="zc"><div class="zl">Tickets Sold</div><div class="zv">0</div></div>
    <div class="zc"><div class="zl">Revenue</div><div class="zv">$0</div></div>
    <div class="zc"><div class="zl">Payouts Out</div><div class="zv">$0</div></div>
    <div class="zc"><div class="zl">Winners</div><div class="zv">0</div></div>
    <div class="zc"><div class="zl">Drawings Run</div><div class="zv">0</div></div>
  </div>
  <div class="pln">⚠ Pre-launch — zero real users, zero real money. Simulation projections are models only.</div>
</div>
<div class="ndiv"></div>

<!-- WINNER TICKER -->
<div class="ticker-wrap">
  <span class="ticker-inner" id="tickerInner">Loading live feed…</span>
</div>

<!-- RAFFLE FLOOR -->
<div class="raffle-floor">
  <div class="floor-title">🎟 THE <span>RAFFLE FLOOR</span> — BUY YOUR TICKETS</div>
  <div class="games-grid" id="gamesGrid"></div>
</div>

<!-- DRAWING HISTORY -->
<div class="draw-history">
  <div class="dh-title">🏆 Recent Drawing Winners</div>
  <div class="dh-grid" id="dhGrid"></div>
</div>

<!-- SCRATCH CARDS -->
<div class="scratch-section">
  <div class="scratch-title">🪙 INSTANT SCRATCH &amp; WIN</div>
  <div class="scratch-grid" id="scratchGrid"></div>
</div>

<div class="ndiv"></div>

<!-- CHARTS TOGGLE -->
<button class="charts-toggle" onclick="toggleCharts()">📊 View Projected Scale Simulation ▼</button>
<div class="charts-body" id="chartsBody">
  <div class="proj-note">PROJECTED MODEL — not real money · pre-launch concept</div>
  <div class="sgap"></div>
  <div class="jp-strip" id="jackpotStrip"></div>
  <div class="sg" id="statsGrid"></div>
  <div class="sslider">
    <div class="sslider-t">Month-by-Month Projection</div>
    <div class="sw">
      <input type="range" id="monthSlider" min="1" max="{{ months }}" value="{{ months }}">
      <div id="monthLabel">Month {{ months }}</div>
    </div>
  </div>
  <div class="cr">
    <div class="cc"><h3>💰 Revenue vs Payouts</h3><canvas id="revChart"></canvas></div>
    <div class="cc"><h3>🎟 Active Recipients</h3><canvas id="recipChart"></canvas></div>
  </div>
  <div class="cr">
    <div class="cc"><h3>📈 Cumulative Revenue</h3><canvas id="cumChart"></canvas></div>
    <div class="cc"><h3>🎯 Tier Split</h3><canvas id="tierPieChart"></canvas></div>
  </div>
</div>

<!-- ABOUT -->
<div class="about-sec">
  <div class="about-t">📖 About Gman's Casino MaxPlus Pro v1.17</div>
  <div class="ag">
    <div class="ac"><h3 style="color:#FFD700;">🎯 What Is This?</h3>
      <p>Global multi-tier raffle. Buy in for $0.25. Every game draws when exactly 1,000,000 tickets are sold. Winners receive monthly annuity payments — not a lump sum. 25% tax is auto-withheld from every payment.</p></div>
    <div class="ac"><h3 style="color:#00ddff;">🎟 The 5 Raffle Games</h3>
      <ul>
        <li><span>$0.25</span> — 5 winners · $8,333/mo × 6mo = $50k each · Pool $250K</li>
        <li><span>$4</span> — 80 winners · $8,333/mo × 6mo = $50k each · Pool $4M</li>
        <li><span>$10</span> — 25 winners · $33,333/mo × 12mo = $400k each · Pool $10M</li>
        <li><span>$100</span> — 200 winners · $83,333/mo × 12mo = $1M each · Pool $100M</li>
        <li><span>$1,000</span> — 2,000 winners · $20,833/mo × 24mo = $500k each · Pool $1B</li>
      </ul></div>
    <div class="ac"><h3 style="color:#00ff55;">📈 Ladder Reinvestment</h3>
      <p>95% of every annuity auto-reinvests into higher-tier tickets. A $0.25 winner earning $8,333/month can automatically buy into the $4, $10, $100, and $1,000 games — for free.</p></div>
    <div class="ac"><h3 style="color:#ff1a44;">💸 Raffle Rules</h3>
      <ul>
        <li>Max <span>10 tickets</span> per person per purchase</li>
        <li>Gift up to <span>10 tickets</span> to a friend per purchase</li>
        <li>Drawing fires at exactly <span>1,000,000 tickets</span> sold</li>
        <li>All entries have <span>equal random odds</span></li>
        <li><span>25% tax</span> withheld on each monthly payout</li>
      </ul></div>
  </div>
</div>

<footer>🎰 Gman's Casino MaxPlus Pro v1.17 — Pre-Launch Concept — Play Responsibly — All simulation figures are mathematical projections only</footer>

<script>
const SIM = {{ sim_data | tojson }};
const GAMES_DATA = {{ games_data | tojson }};
const TC=['#FFD700','#00ddff','#00ff55','#cc44ff','#ff1a44'];
const TB=['#FFA500','#009bcc','#00cc44','#9922dd','#cc0033'];

/* ===== AUDIO ===== */
let AC=null;
function getAC(){if(!AC)AC=new(window.AudioContext||window.webkitAudioContext)();return AC;}
function tone(f,t,v,d,delay=0){
  try{const ac=getAC(),st=ac.currentTime+delay;
    const o=ac.createOscillator(),g=ac.createGain();
    o.connect(g);g.connect(ac.destination);o.type=t;o.frequency.value=f;
    g.gain.setValueAtTime(0,st);g.gain.linearRampToValueAtTime(v,st+.01);
    g.gain.exponentialRampToValueAtTime(.001,st+d);o.start(st);o.stop(st+d);}catch(e){}
}
function sndBall(){tone(600+Math.random()*200,'sine',.14,.18);}
function sndCoin(){[0,.05,.1,.15,.2].forEach((d,i)=>tone(880+i*220,'sine',.15,.2,d));}
function sndFanfare(){[523,659,784,1047,1319].forEach((n,i)=>tone(n,'sine',.18,.4,i*.12));
  setTimeout(()=>[1319,1047,784,659,523].forEach((n,i)=>tone(n,'sine',.14,.3,i*.1)),800);}
function sndBuy(){sndCoin();setTimeout(()=>tone(1200,'sine',.1,.3),200);}
function sndScratch(){for(let i=0;i<8;i++)tone(2000+Math.random()*2000,'sawtooth',.04,.04,i*.03);}
function sndDrum(){for(let i=0;i<3;i++)tone(100-i*20,'square',.18,.12,i*.08);}
document.addEventListener('click',()=>{try{getAC().resume();}catch(e){}},{once:true});

/* ===== BG PARTICLES ===== */
const bgC=document.getElementById('bgCanvas'),bgX=bgC.getContext('2d');
let bparts=[];
function initBG(){bgC.width=window.innerWidth;bgC.height=window.innerHeight;bparts=[];
  for(let i=0;i<100;i++)bparts.push({x:Math.random()*bgC.width,y:Math.random()*bgC.height,
    r:Math.random()*1.4+.3,vx:(Math.random()-.5)*.25,vy:-(Math.random()*.3+.08),
    c:['#FFD70022','#ff224422','#00ff5522','#00ddff22','#ee00ff22'][i%5],life:Math.random()});}
function animBG(){bgX.clearRect(0,0,bgC.width,bgC.height);
  bparts.forEach(p=>{p.x+=p.vx;p.y+=p.vy;p.life+=.004;
    if(p.y<-10||p.life>1){p.y=bgC.height+5;p.x=Math.random()*bgC.width;p.life=0;}
    bgX.beginPath();bgX.arc(p.x,p.y,p.r,0,Math.PI*2);bgX.fillStyle=p.c;bgX.fill();});
  requestAnimationFrame(animBG);}
window.addEventListener('resize',initBG);initBG();animBG();

/* ===== SIGN BULBS ===== */
function buildBulbs(){
  ['topBulbs','botBulbs'].forEach(id=>{
    const el=document.getElementById(id);
    const cls=['r','g','b','y','p'];
    for(let i=0;i<18;i++){const d=document.createElement('div');
      d.className='blb '+cls[i%cls.length];d.style.animationDelay=(i*.1)+'s';el.appendChild(d);}
  });
}
buildBulbs();
setInterval(()=>{const s=document.querySelector('.sign-frame');if(Math.random()<.03){s.style.opacity='.65';setTimeout(()=>{s.style.opacity='1';},55);setTimeout(()=>{if(Math.random()<.5){s.style.opacity='.85';setTimeout(()=>s.style.opacity='1',40);}},110);}},450);

/* ===== CONFETTI ===== */
const confC=document.getElementById('confCanvas'),confX=confC.getContext('2d');
let cparts=[],crun=false;
function startConfetti(){
  confC.width=window.innerWidth;confC.height=window.innerHeight;confC.className='show';cparts=[];
  const col=['#FFD700','#ff1a44','#00ff55','#00ddff','#ee00ff','#fff','#FFA500'];
  for(let i=0;i<200;i++)cparts.push({x:Math.random()*confC.width,y:-15-Math.random()*250,
    vx:(Math.random()-.5)*5,vy:Math.random()*5+3,r:Math.random()*5+3,
    c:col[i%col.length],rot:Math.random()*360,rv:(Math.random()-.5)*7});
  crun=true;animConf();}
function animConf(){if(!crun)return;confX.clearRect(0,0,confC.width,confC.height);
  let a=0;cparts.forEach(p=>{p.x+=p.vx;p.y+=p.vy;p.rot+=p.rv;p.vy+=.12;
    if(p.y<confC.height+10)a++;confX.save();confX.translate(p.x,p.y);confX.rotate(p.rot*Math.PI/180);
    confX.fillStyle=p.c;confX.fillRect(-p.r/2,-p.r/2,p.r,p.r*2);confX.restore();});
  if(a>0)requestAnimationFrame(animConf);else{confC.className='';crun=false;}}

/* ===== WIN POPUP ===== */
function showWin(title,msg,conf=true){
  document.getElementById('winTitle').textContent=title;
  document.getElementById('winMsg').textContent=msg;
  document.getElementById('winOverlay').className='show';
  sndFanfare();if(conf)startConfetti();}
function closeWin(){document.getElementById('winOverlay').className='';crun=false;confC.className='';}

/* ===== TICKER ===== */
const TMSGS=[
  '🏆 TK-4A9F2 WON $50,000 in the $0.25 Raffle — now receiving $8,333/month!',
  '🎟 TK-BB301 entered 10 tickets into the $4M Raffle Game!',
  '🎁 TK-99C11 gifted 5 raffle tickets to a friend — $250,000 pool!',
  '💰 TK-2D8E4 entered the $1,000 ELITE Raffle — $1 BILLION prize pool!',
  '🏆 TK-71FAA is collecting $8,333/month for 6 months — $50,000 total!',
  '⚡ ALERT: $100 Raffle — drawing in only 8,400 more tickets!',
  '🎟 TK-CC881 just entered the $10 Raffle — chance to win $400,000!',
  '💸 TK-55A22 receiving $33,333/month for 12 months — $400K prize!',
  '🎁 10 gift raffle tickets sent — TK-D0291 to TK-D029A!',
  '🔥 TK-F9A10 bought all 10 tickets in the $1,000 Billion Raffle!',
  '🏆 TK-8B443 — $1,000,000 annuity: $83,333/month for 12 months!',
  '📢 NEW DRAWING: $4 Raffle just fired — 80 new winners selected!',
];
function refreshTicker(){
  const el=document.getElementById('tickerInner');
  el.innerHTML=[...TMSGS].sort(()=>Math.random()-.5).map(t=>`<span style="color:${['#FFD700','#00ff55','#00ddff','#ee00ff','#ff9900'][Math.floor(Math.random()*5)]}">${t}</span>`).join('&nbsp;&nbsp;·&nbsp;&nbsp;');
}
refreshTicker();setInterval(refreshTicker,28000);

/* ===== GAME DEFINITIONS ===== */
const GDEFS=[
  {id:'025',price:.25,label:'$0.25',name:'QUARTER RUSH RAFFLE',winners:5,payout:'$8,333/mo',dur:'6 months',total:'$50,000',pool:'$250,000',poolFull:250000,
   accent:'#b8ff44',bg:'linear-gradient(180deg,#0a1e04,#06100a)',border:'#2a6600',
   btnBg:'linear-gradient(135deg,#2a5500,#44aa00,#2a5500)',btnCol:'#ccff88',bulbCol:'#b8ff44',
   ballColors:['#3a8800','#2a6600','#1e4400','#4aaa00','#55cc00'],
   desc:'Win $50,000 paid as $8,333/month for 6 months'},
  {id:'4',price:4,label:'$4',name:'BLUE DIAMOND RAFFLE',winners:80,payout:'$8,333/mo',dur:'6 months',total:'$50,000',pool:'$4,000,000',poolFull:4000000,
   accent:'#00ddff',bg:'linear-gradient(180deg,#001828,#000e18)',border:'#004488',
   btnBg:'linear-gradient(135deg,#001a44,#0055cc,#001a44)',btnCol:'#88ccff',bulbCol:'#00ddff',
   ballColors:['#003388','#0044aa','#0055cc','#0033aa','#001166'],
   desc:'Win $50,000 paid as $8,333/month for 6 months'},
  {id:'10',price:10,label:'$10',name:'GREEN GIANT RAFFLE',winners:25,payout:'$33,333/mo',dur:'12 months',total:'$400,000',pool:'$10,000,000',poolFull:10000000,
   accent:'#00ff55',bg:'linear-gradient(180deg,#031a08,#020c04)',border:'#006622',
   btnBg:'linear-gradient(135deg,#004422,#009933,#004422)',btnCol:'#88ffaa',bulbCol:'#00ff55',
   ballColors:['#006622','#008833','#00aa44','#004418','#009900'],
   desc:'Win $400,000 paid as $33,333/month for 12 months'},
  {id:'100',price:100,label:'$100',name:'GOLDEN VAULT RAFFLE',winners:200,payout:'$83,333/mo',dur:'12 months',total:'$1,000,000',pool:'$100,000,000',poolFull:100000000,
   accent:'#FFD700',bg:'linear-gradient(180deg,#1a1002,#0c0800)',border:'#886600',
   btnBg:'linear-gradient(135deg,#886600,#FFD700,#886600)',btnCol:'#1a0800',bulbCol:'#FFD700',
   ballColors:['#886600','#aa8800','#cc9900','#775500','#bb9900'],
   desc:'Win $1,000,000 paid as $83,333/month for 12 months'},
  {id:'1000',price:1000,label:'$1,000',name:'BILLION DOLLAR ELITE',winners:2000,payout:'$20,833/mo',dur:'24 months',total:'$500,000',pool:'$1,000,000,000',poolFull:1000000000,
   accent:'#ff1a44',bg:'linear-gradient(180deg,#1a0008,#0c0004)',border:'#880022',
   btnBg:'linear-gradient(135deg,#880022,#ff1a44,#880022)',btnCol:'#ffaacc',bulbCol:'#ff1a44',
   ballColors:['#880022','#aa0030','#cc0040','#660018','#bb0035'],
   desc:'Win $500,000 paid as $20,833/month for 24 months'},
];

/* ===== STATE ===== */
const state={};
GDEFS.forEach(g=>state[g.id]={tickets:0,giftTix:0,pct:20+Math.random()*50,myBalls:[]});

/* ===== BUILD GAME CARDS ===== */
function buildGameCard(g){
  const s=state[g.id];
  const pct=s.pct.toFixed(1);
  const ticketsSold=Math.floor(1000000*s.pct/100);

  let bulbHtml='';
  for(let i=0;i<18;i++) bulbHtml+=`<div class="rb" style="color:${g.bulbCol};background:${g.bulbCol};animation-delay:${(i%5)*.22}s"></div>`;

  return `
  <div class="rgame" style="border-color:${g.border};background:${g.bg};">
    <div class="rg-head">
      <div class="rg-game-name" style="color:${g.accent}">${g.name}</div>
      <div class="rg-price" style="color:${g.accent}">${g.label} ENTRY</div>
      <div class="rg-pool">PRIZE POOL: ${g.pool}</div>
    </div>
    <div class="rg-bulbs">${bulbHtml}</div>
    <div class="rg-body">

      <!-- BALL MACHINE -->
      <div class="ball-machine">
        <div class="bm-top">
          <span class="bm-label">🎱 YOUR TICKET NUMBERS</span>
          <span class="bm-status open" id="status-${g.id}">ENTRIES OPEN</span>
        </div>
        <div class="balls-display" id="balls-${g.id}">
          <span class="ball-placeholder">Buy tickets to see your entry numbers →</span>
        </div>
      </div>

      <!-- TICKET COUNTER PROGRESS -->
      <div class="tix-progress">
        <div class="tix-progress-top">
          <span>Tickets sold toward drawing</span>
          <span class="hot" style="color:${g.accent}" id="pctlbl-${g.id}">${pct}% · ${ticketsSold.toLocaleString()} / 1,000,000</span>
        </div>
        <div class="prog-bg">
          <div class="prog-fill" id="progfill-${g.id}" style="width:${pct}%;background:linear-gradient(90deg,${g.accent}66,${g.accent});"></div>
        </div>
      </div>

      <!-- GAME STATS -->
      <div class="rg-stats">
        <div class="rs-row"><span class="rs-l">Winners per Drawing</span><span class="rs-v hl" style="color:${g.accent}">${g.winners.toLocaleString()}</span></div>
        <div class="rs-row"><span class="rs-l">Monthly Payout / Winner</span><span class="rs-v hl">${g.payout}</span></div>
        <div class="rs-row"><span class="rs-l">Payout Duration</span><span class="rs-v">${g.dur}</span></div>
        <div class="rs-row"><span class="rs-l">Total Per Winner</span><span class="rs-v hl">${g.total}</span></div>
        <div class="rs-row"><span class="rs-l">Max Tickets / Purchase</span><span class="rs-v">10 buy + 10 gift</span></div>
        <div class="rs-row"><span class="rs-l">Tax Withheld</span><span class="rs-v">25% per payment</span></div>
      </div>

      <!-- BUY PANEL -->
      <div class="buy-panel">
        <div class="bp-title">🎟 BUY RAFFLE TICKETS — ${g.desc}</div>
        <div class="bp-row"><span class="bp-lbl">For Me</span><input class="bp-qty" type="number" min="1" max="10" value="1" id="qty-${g.id}" oninput="updCost('${g.id}',${g.price})"></div>
        <div class="bp-row"><span class="bp-lbl">Gift</span><input class="bp-qty" type="number" min="0" max="10" value="0" id="gift-${g.id}" oninput="updCost('${g.id}',${g.price})"></div>
        <div class="bp-cost" id="cost-${g.id}">Total: <span>$${g.price.toFixed(2)}</span></div>
        <button class="btn-buy" style="background:${g.btnBg};color:${g.btnCol};box-shadow:0 0 18px ${g.accent}44,0 4px 14px rgba(0,0,0,.5);" onclick="buyTickets('${g.id}',${g.price})">🎟 BUY RAFFLE TICKETS</button>
        <button class="btn-gift" onclick="giftTickets('${g.id}',${g.price})">🎁 GIFT TICKETS TO A FRIEND</button>
        <div class="bp-result" id="bpr-${g.id}"></div>
        <div class="ticket-stubs" id="stubs-${g.id}"></div>
      </div>
    </div>
  </div>`;
}

document.getElementById('gamesGrid').innerHTML = GDEFS.map(buildGameCard).join('');

/* ===== TICKET PROGRESS ANIMATION ===== */
setInterval(()=>{
  GDEFS.forEach(g=>{
    const s=state[g.id];
    s.pct=Math.min(99.5, s.pct + Math.random()*.6);
    const el=document.getElementById('progfill-'+g.id);
    const lbl=document.getElementById('pctlbl-'+g.id);
    if(el){el.style.width=s.pct.toFixed(1)+'%';}
    if(lbl){
      const sold=Math.floor(1000000*s.pct/100);
      lbl.textContent=s.pct.toFixed(1)+'% · '+sold.toLocaleString()+' / 1,000,000';
    }
    if(s.pct>=99.5){
      s.pct=5+Math.random()*15;
      const st=document.getElementById('status-'+g.id);
      if(st){st.textContent='DRAWING!';st.className='bm-status drawing';}
      setTimeout(()=>{
        fireDrawing(g);
        if(st){st.textContent='ENTRIES OPEN';st.className='bm-status open';}
      },1200);
    }
  });
},700);

/* ===== FIRE DRAWING ===== */
function fireDrawing(g){
  sndDrum();
  const winners=[];
  for(let i=0;i<Math.min(5,g.winners);i++){
    winners.push('TK-'+Math.random().toString(36).substr(2,6).toUpperCase());
  }
  showWin(`🎰 DRAWING FIRED! ${g.name}`,
    `${g.winners.toLocaleString()} winners selected!\nTop entries: ${winners.slice(0,3).join(' · ')}\nEach winner receives ${g.payout} for ${g.dur} (${g.total} total)`);
  updateDrawHistory();
}

/* ===== DRAWING HISTORY ===== */
const drawHistory=[];
function genHistory(){
  GDEFS.forEach(g=>{
    for(let i=0;i<3;i++){
      const n=Math.floor(Math.random()*99)+1;
      const clr=g.ballColors[Math.floor(Math.random()*g.ballColors.length)];
      drawHistory.push({
        game:g.name,accent:g.accent,ballColor:clr,
        tk:'TK-'+Math.random().toString(36).substr(2,6).toUpperCase(),
        num:n, prize:g.total, payout:g.payout
      });
    }
  });
}
genHistory();
function updateDrawHistory(){
  // add a fresh entry
  const g=GDEFS[Math.floor(Math.random()*GDEFS.length)];
  const clr=g.ballColors[Math.floor(Math.random()*g.ballColors.length)];
  drawHistory.unshift({game:g.name,accent:g.accent,ballColor:clr,
    tk:'TK-'+Math.random().toString(36).substr(2,6).toUpperCase(),
    num:Math.floor(Math.random()*99)+1,prize:g.total,payout:g.payout});
  if(drawHistory.length>30)drawHistory.pop();
  renderHistory();
}
function renderHistory(){
  document.getElementById('dhGrid').innerHTML=GDEFS.map(g=>{
    const entries=drawHistory.filter(d=>d.game===g.name).slice(0,4);
    if(!entries.length)return '';
    return `<div class="dh-card">
      <div class="dh-card-title" style="color:${g.accent}">${g.name} — Recent Winners</div>
      ${entries.map(e=>`
        <div class="dh-winner">
          <div class="dh-num" style="background:${e.ballColor};color:#fff;">${e.num}</div>
          <span class="dh-tk">${e.tk}</span>
          <span class="dh-prize">${e.prize}</span>
        </div>`).join('')}
    </div>`;
  }).join('');
}
renderHistory();

/* ===== BUY TICKETS ===== */
function genTK(){return 'TK-'+Math.random().toString(36).substr(2,6).toUpperCase();}
function randNum(max){return Math.floor(Math.random()*max)+1;}

function updCost(id,price){
  const q=Math.min(10,Math.max(0,parseInt(document.getElementById('qty-'+id).value)||0));
  const gf=Math.min(10,Math.max(0,parseInt(document.getElementById('gift-'+id).value)||0));
  document.getElementById('cost-'+id).innerHTML='Total: <span>$'+((q+gf)*price).toLocaleString('en-US',{minimumFractionDigits:2})+'</span>';
}

function addBalls(id,count,g,isGift){
  const container=document.getElementById('balls-'+id);
  const placeholder=container.querySelector('.ball-placeholder');
  if(placeholder)placeholder.remove();
  const s=state[id];
  for(let i=0;i<count;i++){
    const num=randNum(1000000);
    const clr=g.ballColors[i%g.ballColors.length];
    const b=document.createElement('div');
    b.className='ball'+(isGift?' ':'  my');
    b.style.background=`radial-gradient(circle at 35% 35%, ${clr}dd, ${clr})`;
    b.style.color='#fff';
    b.style.animationDelay=(i*.08)+'s';
    b.title='Ticket #'+num.toLocaleString();
    b.textContent=num>999?Math.floor(num/1000)+'K':num;
    container.appendChild(b);
    setTimeout(()=>sndBall(),i*80);
    if(!isGift)s.myBalls.push(num);
  }
  // keep max 10 visible
  const balls=container.querySelectorAll('.ball');
  if(balls.length>10) balls[0].remove();
}

function showBPR(id,msg,cls){
  const el=document.getElementById('bpr-'+id);el.className='bp-result show '+cls;el.textContent=msg;
  setTimeout(()=>el.className='bp-result',5500);
}

function renderStubsEl(id,my,gf){
  const g=GDEFS.find(x=>x.id===id);
  let h='';
  for(let i=0;i<my;i++){
    const tk=genTK();const num=randNum(1000000);
    h+=`<div class="tstub"><span class="tnum">${tk}</span> #${num.toLocaleString()}</div>`;
  }
  for(let i=0;i<gf;i++){
    const tk=genTK();const num=randNum(1000000);
    h+=`<div class="tstub gift"><span class="tnum">🎁 ${tk}</span> #${num.toLocaleString()}</div>`;
  }
  document.getElementById('stubs-'+id).innerHTML=h;
}

function buyTickets(id,price){
  const g=GDEFS.find(x=>x.id===id);
  const my=Math.min(10,Math.max(1,parseInt(document.getElementById('qty-'+id).value)||1));
  const gf=Math.min(10,Math.max(0,parseInt(document.getElementById('gift-'+id).value)||0));
  const total=(my+gf)*price;
  state[id].tickets+=my;
  addBalls(id,my,g,false);
  if(gf>0)addBalls(id,gf,g,true);
  renderStubsEl(id,my,gf);
  sndBuy();
  let msg=`✅ ${my} ticket${my>1?'s':''} entered into ${g.name} — $${total.toFixed(2)}`;
  if(gf>0)msg+=` · ${gf} gifted`;
  showBPR(id,msg,'ok');
  if(Math.random()<.09)setTimeout(()=>showWin('🎉 EARLY MATCH!','Ticket '+genTK()+' pre-matched for '+g.name+'! Annuity of '+g.payout+' for '+g.dur+' if confirmed at drawing!'),800);
}

function giftTickets(id,price){
  const g=GDEFS.find(x=>x.id===id);
  const gf=Math.min(10,Math.max(1,parseInt(document.getElementById('gift-'+id).value)||1));
  document.getElementById('qty-'+id).value=0;updCost(id,price);
  addBalls(id,gf,g,true);
  renderStubsEl(id,0,gf);
  sndCoin();
  showBPR(id,`🎁 ${gf} gift ticket${gf>1?'s':''} — $${(gf*price).toFixed(2)} — Share your link!`,'gk');
}

/* ===== SCRATCH CARDS ===== */
const SC=[
  {prize:'$0.25 ENTRY',sub:'Quarter Rush Raffle',c:'#0a1e04',a:'#b8ff44'},
  {prize:'$4 ENTRY',sub:'Blue Diamond Raffle',c:'#001828',a:'#00ddff'},
  {prize:'$10 ENTRY',sub:'Green Giant Raffle',c:'#031a08',a:'#00ff55'},
  {prize:'$100 ENTRY',sub:'Golden Vault Raffle',c:'#1a1002',a:'#FFD700'},
  {prize:'$1,000 ENTRY',sub:'Billion Dollar Elite',c:'#1a0008',a:'#ff1a44'},
  {prize:'2× TICKETS',sub:'Double Entry Bonus',c:'#140025',a:'#ee00ff'},
];
let scState={};
function buildScratch(){
  document.getElementById('scratchGrid').innerHTML=SC.map((p,i)=>`
    <div class="sc-card" onclick="doScratch(${i})">
      <div class="sc-bg" style="background:linear-gradient(135deg,${p.c},${p.c}cc);">
        <div class="sc-prize" style="color:${p.a};text-shadow:0 0 10px ${p.a}">${p.prize}</div>
        <div class="sc-sub">${p.sub}</div>
      </div>
      <div class="sc-foil" id="scf-${i}"><span style="font-size:1.5rem">🪙</span><span style="font-size:.7rem;letter-spacing:2px">SCRATCH</span></div>
    </div>`).join('');
  scState={};
}
function doScratch(i){
  if(scState[i])return;scState[i]=true;sndScratch();
  document.getElementById('scf-'+i).classList.add('scratched');
  setTimeout(()=>{const p=SC[i];showWin('🪙 SCRATCH WIN!',p.prize+' — '+p.sub+'\nBuy tickets to enter the drawing!');},480);
}
buildScratch();
setInterval(()=>{if(SC.every((_,i)=>scState[i]))setTimeout(buildScratch,3200);},3600);

/* ===== CHARTS (lazy) ===== */
let chartsBuilt=false;
function toggleCharts(){
  const b=document.getElementById('chartsBody');b.classList.toggle('open');
  if(b.classList.contains('open')&&!chartsBuilt){buildCharts();chartsBuilt=true;}
}
const labels=SIM.map(d=>'M'+d.month);
let tierChart=null;
function mkC(id,type,ds,opts={}){
  return new Chart(document.getElementById(id).getContext('2d'),{type,data:{labels,datasets:ds},
    options:{responsive:true,animation:{duration:200},
      plugins:{legend:{labels:{color:'#555',font:{size:9}}}},
      scales:type!='doughnut'?{x:{ticks:{color:'#333',maxTicksLimit:10},grid:{color:'rgba(255,255,255,.025)'}},y:{ticks:{color:'#444'},grid:{color:'rgba(255,255,255,.025)'}}}:{}}});}
function buildCharts(){
  mkC('revChart','line',[
    {label:'Revenue',data:SIM.map(d=>d.monthly_revenue),borderColor:'#FFD700',backgroundColor:'rgba(255,215,0,.07)',fill:true,tension:.4,pointRadius:0},
    {label:'Payouts',data:SIM.map(d=>d.monthly_payouts),borderColor:'#00ff55',backgroundColor:'rgba(0,255,80,.05)',fill:true,tension:.4,pointRadius:0},
    {label:'Net',data:SIM.map(d=>d.net_to_winners),borderColor:'#00ddff',backgroundColor:'rgba(0,200,255,.04)',fill:true,tension:.4,pointRadius:0}]);
  mkC('recipChart','line',[{label:'Active Recipients',data:SIM.map(d=>d.active_recipients_total),borderColor:'#cc44ff',backgroundColor:'rgba(180,0,255,.08)',fill:true,tension:.4,pointRadius:0}]);
  mkC('cumChart','line',[
    {label:'Cum Revenue',data:SIM.map(d=>d.cumulative_revenue),borderColor:'#FFD700',backgroundColor:'rgba(255,215,0,.06)',fill:true,tension:.4,pointRadius:0},
    {label:'Cum Payouts',data:SIM.map(d=>d.cumulative_payouts),borderColor:'#ff1a44',backgroundColor:'rgba(255,0,40,.05)',fill:true,tension:.4,pointRadius:0}]);
  tierChart=new Chart(document.getElementById('tierPieChart').getContext('2d'),{type:'doughnut',
    data:{labels:GAMES_DATA.map(g=>'$'+g.name),datasets:[{data:GAMES_DATA.map(g=>0),backgroundColor:TC,borderColor:TB,borderWidth:2}]},
    options:{responsive:true,plugins:{legend:{labels:{color:'#666'}}}}});
  updateDash(SIM.length-1);
}
function fmt(n){return n>=1e12?'$'+(n/1e12).toFixed(2)+'T':n>=1e9?'$'+(n/1e9).toFixed(2)+'B':n>=1e6?'$'+(n/1e6).toFixed(1)+'M':'$'+n.toLocaleString();}
function fmtN(n){return n>=1e9?(n/1e9).toFixed(2)+'B':n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(0)+'K':n.toLocaleString();}
function updateDash(idx){
  const d=SIM[idx];document.getElementById('monthLabel').textContent='Month '+d.month;
  document.getElementById('statsGrid').innerHTML=`
    <div class="sc-stat"><div class="sl">Players</div><div class="sv bl">${fmtN(d.players)}</div></div>
    <div class="sc-stat"><div class="sl">Revenue</div><div class="sv go">${fmt(d.monthly_revenue)}</div></div>
    <div class="sc-stat"><div class="sl">Payouts</div><div class="sv gr">${fmt(d.monthly_payouts)}</div></div>
    <div class="sc-stat"><div class="sl">Taxes</div><div class="sv rd">${fmt(d.taxes_collected)}</div></div>
    <div class="sc-stat"><div class="sl">Net Winners</div><div class="sv go">${fmt(d.net_to_winners)}</div></div>
    <div class="sc-stat"><div class="sl">Recipients</div><div class="sv pu">${fmtN(d.active_recipients_total)}</div></div>
    <div class="sc-stat"><div class="sl">Happiness</div><div class="sv gr">${fmtN(d.happiness_impact)}</div></div>
    <div class="sc-stat"><div class="sl">Drawings</div><div class="sv bl">${fmtN(d.drawings_total)}</div></div>`;
  document.getElementById('jackpotStrip').innerHTML=`
    <div class="jp">Cum Revenue: <span>${fmt(d.cumulative_revenue)}</span></div>
    <div class="jp">Cum Payouts: <span>${fmt(d.cumulative_payouts)}</span></div>
    <div class="jp">Active Winners: <span>${fmtN(GAMES_DATA.reduce((s,g)=>s+(d[g.name+'_active_recipients']||0),0))}</span></div>`;
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