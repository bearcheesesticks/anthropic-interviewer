#!/usr/bin/env python3
"""
Anthropic Interviewer - CLI for conducting AI-powered qualitative research.

Usage:
    python main.py plan              Create an interview rubric
    python main.py interview         Conduct an interview
    python main.py analyze           Analyze collected transcripts
    python main.py demo              Run a full demo workflow
"""

import sys
import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.markdown import Markdown
from rich.table import Table
from anthropic import Anthropic

from agents import (
    PlanningAgent,
    ResearchStudy,
    InterviewAgent,
    AdaptiveInterviewAgent,
    AnalysisAgent,
    ProbeAction,
)
from storage import TranscriptStore, StorageConfig

console = Console()


def create_rubric():
    """Interactive rubric creation workflow."""
    console.print(Panel("📋 Interview Rubric Planning", style="bold blue"))

    # Gather study information
    console.print("\n[bold]Define your research study:[/bold]\n")

    goals = []
    console.print("Enter research goals (empty line to finish):")
    while True:
        goal = Prompt.ask("  Goal", default="")
        if not goal:
            break
        goals.append(goal)

    if not goals:
        console.print("[red]At least one research goal is required.[/red]")
        return

    population = Prompt.ask("\nTarget population")
    duration = int(Prompt.ask("Target interview duration (minutes)", default="15"))

    hypotheses = []
    if Confirm.ask("\nDo you have specific hypotheses?", default=False):
        console.print("Enter hypotheses (empty line to finish):")
        while True:
            hyp = Prompt.ask("  Hypothesis", default="")
            if not hyp:
                break
            hypotheses.append(hyp)

    context = Prompt.ask("\nAny additional context", default="")

    # Create the study configuration
    study = ResearchStudy(
        research_goals=goals,
        target_population=population,
        hypotheses=hypotheses if hypotheses else None,
        duration_minutes=duration,
        additional_context=context,
    )

    console.print("\n[yellow]Generating interview rubric...[/yellow]")

    client = Anthropic()
    planner = PlanningAgent(client)
    rubric = planner.create_rubric(study)

    # Display the rubric
    console.print(Panel("Generated Interview Rubric", style="bold green"))
    console.print(f"\n[bold]Study:[/bold] {rubric.study_title}")
    console.print(f"[bold]Duration:[/bold] {rubric.target_duration_minutes} minutes")

    console.print("\n[bold]Sections:[/bold]")
    for section in rubric.sections:
        console.print(f"\n  [cyan]{section.get('name', 'Unnamed')}[/cyan]")
        console.print(f"  Purpose: {section.get('purpose', 'N/A')}")
        for q in section.get("questions", []):
            console.print(f"    • {q.get('text', '')}")

    # Save the rubric
    if Confirm.ask("\nSave this rubric?", default=True):
        study_name = Prompt.ask("Study name (for storage)", default="my_study")
        config = StorageConfig(Path("./data"), study_name)
        store = TranscriptStore(config)
        path = store.save_rubric(rubric.to_json())
        console.print(f"[green]Saved to {path}[/green]")

    return rubric


def conduct_interview():
    """Interactive interview workflow."""
    console.print(Panel("🎤 Conduct Interview", style="bold blue"))

    # Load or create rubric
    study_name = Prompt.ask("Study name", default="my_study")
    config = StorageConfig(Path("./data"), study_name)
    store = TranscriptStore(config)

    try:
        rubric_data = store.load_rubric()
        console.print("[green]Loaded existing rubric.[/green]")
    except FileNotFoundError:
        console.print("[red]No rubric found. Please create one first with 'plan'.[/red]")
        return

    from agents.planning import InterviewRubric

    rubric = InterviewRubric.from_json(rubric_data)

    participant_id = Prompt.ask("Participant ID")
    context = Prompt.ask("Participant context (optional)", default="")

    client = Anthropic()
    interviewer = InterviewAgent(client)

    # Start the interview
    session = interviewer.start_session(
        rubric=rubric,
        participant_id=participant_id,
        participant_context=context,
    )

    console.print(Panel("Interview Started - Type 'quit' to end", style="bold green"))
    console.print()

    # Display opening
    console.print(f"[bold cyan]Interviewer:[/bold cyan] {session.messages[-1].content}\n")

    # Interview loop
    while not session.ended_at:
        response = Prompt.ask("[bold yellow]You[/bold yellow]")

        if response.lower() in ["quit", "exit", "end"]:
            session = interviewer.end_session(session)
            console.print(
                f"\n[bold cyan]Interviewer:[/bold cyan] {session.messages[-1].content}"
            )
            break

        interviewer_response = interviewer.respond(session, response)
        console.print(f"\n[bold cyan]Interviewer:[/bold cyan] {interviewer_response}\n")

    # Save the transcript
    path = store.save_session(session)
    console.print(f"\n[green]Transcript saved to {path}[/green]")

    # Show stats
    stats = store.get_stats()
    console.print(f"Total interviews in study: {stats['total_sessions']}")

    return session


def analyze_transcripts():
    """Analyze collected transcripts."""
    console.print(Panel("📊 Analyze Transcripts", style="bold blue"))

    study_name = Prompt.ask("Study name", default="my_study")
    config = StorageConfig(Path("./data"), study_name)
    store = TranscriptStore(config)

    sessions = store.load_all_sessions()

    if not sessions:
        console.print("[red]No transcripts found for this study.[/red]")
        return

    console.print(f"Found {len(sessions)} transcripts.")

    # Get research context
    research_context = Prompt.ask("Brief research context")

    questions = []
    console.print("Enter research questions (empty line to finish):")
    while True:
        q = Prompt.ask("  RQ", default="")
        if not q:
            break
        questions.append(q)

    if not questions:
        questions = ["What are the main themes in these interviews?"]

    console.print("\n[yellow]Analyzing transcripts...[/yellow]")

    client = Anthropic()
    analyzer = AnalysisAgent(client)

    # Analyze
    individual_analyses, theme_analysis = analyzer.batch_analyze(
        sessions=sessions,
        research_context=research_context,
        research_questions=questions,
    )

    # Save analyses
    for analysis in individual_analyses:
        store.save_transcript_analysis(analysis)

    theme_path = store.save_theme_analysis(theme_analysis)

    # Display results
    console.print(Panel("Analysis Complete", style="bold green"))
    console.print(Markdown(theme_analysis.get_theme_summary()))

    console.print(f"\n[green]Theme analysis saved to {theme_path}[/green]")

    # Offer export
    if Confirm.ask("\nExport transcripts to Parquet?", default=False):
        parquet_path = store.export_to_parquet()
        console.print(f"[green]Exported to {parquet_path}[/green]")

    return theme_analysis


def run_demo():
    """Run a complete demo workflow."""
    console.print(Panel("🚀 Anthropic Interviewer Demo", style="bold magenta"))

    console.print(
        """
This demo will:
1. Create a sample interview rubric about AI usage at work
2. Conduct a short simulated interview
3. Analyze the transcript

"""
    )

    if not Confirm.ask("Continue?", default=True):
        return

    client = Anthropic()

    # Step 1: Create rubric
    console.print("\n" + "=" * 60)
    console.print("[bold]Step 1: Creating Interview Rubric[/bold]")
    console.print("=" * 60 + "\n")

    study = ResearchStudy(
        research_goals=[
            "Understand how professionals integrate AI tools into their daily work",
            "Identify pain points and satisfactions with current AI tools",
            "Explore concerns about AI's impact on their profession",
        ],
        target_population="Knowledge workers who use AI tools at least weekly",
        hypotheses=[
            "Users feel tension between AI efficiency and maintaining their skills",
            "Trust in AI varies significantly by task type",
        ],
        duration_minutes=10,
        additional_context="Focus on practical, day-to-day experiences rather than abstract opinions.",
    )

    planner = PlanningAgent(client)
    rubric = planner.create_rubric(study)

    console.print(f"[green]✓ Created rubric: {rubric.study_title}[/green]")
    console.print(f"  {len(rubric.get_all_questions())} questions across {len(rubric.sections)} sections")

    # Save rubric
    config = StorageConfig(Path("./data"), "demo_study")
    store = TranscriptStore(config)
    store.save_rubric(rubric.to_json())

    # Step 2: Conduct interview
    console.print("\n" + "=" * 60)
    console.print("[bold]Step 2: Conducting Interview[/bold]")
    console.print("=" * 60 + "\n")

    interviewer = InterviewAgent(client)
    session = interviewer.start_session(
        rubric=rubric,
        participant_id="demo_participant_001",
        participant_context="Software developer at a mid-size tech company, uses AI daily for coding assistance.",
    )

    console.print("[cyan]Interviewer:[/cyan]", session.messages[-1].content)
    console.print()

    # Simulated participant responses
    demo_responses = [
        "I use AI pretty much every day, mainly for coding. Things like autocomplete, generating boilerplate, sometimes debugging. It's become hard to imagine working without it honestly.",
        "The biggest frustration is when it's confidently wrong. Like it'll generate code that looks perfect but has subtle bugs. I've learned to never trust it completely - always review everything.",
        "That's a good question. I do worry sometimes that I'm not learning as deeply as I used to. Before AI, I'd really dig into documentation and figure things out. Now I just ask Claude and move on. It's faster but... I'm not sure it's better for my growth.",
        "I think the key is using it as a collaborator, not a replacement. I still need to understand what it's doing. The developers who just copy-paste without understanding are going to struggle. But if you use it to augment your thinking, it's incredibly powerful.",
        "I'd say my relationship with AI is cautiously optimistic. It's made me more productive for sure, but I'm intentional about still doing things the hard way sometimes, just to keep my skills sharp. Balance is important.",
    ]

    for response in demo_responses:
        console.print(f"[yellow]Participant:[/yellow] {response}\n")
        interviewer_response = interviewer.respond(session, response)
        console.print(f"[cyan]Interviewer:[/cyan] {interviewer_response}\n")

        if session.ended_at:
            break

    if not session.ended_at:
        session = interviewer.end_session(session)

    store.save_session(session)
    console.print(f"[green]✓ Interview completed: {len(session.messages)} messages[/green]")

    # Step 3: Analyze
    console.print("\n" + "=" * 60)
    console.print("[bold]Step 3: Analyzing Transcript[/bold]")
    console.print("=" * 60 + "\n")

    analyzer = AnalysisAgent(client)

    individual, themes = analyzer.batch_analyze(
        sessions=[session],
        research_context="Study of AI integration in knowledge work",
        research_questions=[
            "How do professionals integrate AI into their workflows?",
            "What concerns do they have about AI's impact?",
            "How do they balance efficiency with skill development?",
        ],
    )

    store.save_transcript_analysis(individual[0])
    store.save_theme_analysis(themes)

    console.print("[green]✓ Analysis complete[/green]\n")
    console.print(Markdown(themes.get_theme_summary()))

    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold]Demo Complete![/bold]")
    console.print("=" * 60)

    table = Table(title="Generated Artifacts")
    table.add_column("Artifact", style="cyan")
    table.add_column("Location", style="green")

    table.add_row("Interview Rubric", str(config.rubrics_path / "rubric_v1.json"))
    table.add_row("Transcript", str(config.transcripts_path))
    table.add_row("Analysis", str(config.analyses_path))

    console.print(table)


def run_interactive():
    """Fully interactive interview with adaptive probing - YOU are the participant."""
    console.print(Panel("🎙️ Interactive Adaptive Interview", style="bold magenta"))

    console.print(
        """
[bold]You will be interviewed by an AI interviewer.[/bold]

After each of your responses, you'll see:
- 🔍 What signals were detected in your response
- 🧠 What probe action was chosen and why
- 📊 Interview progress (coverage, depth, time)

Type [bold]'quit'[/bold] at any time to end the interview.
"""
    )

    client = Anthropic()

    # Step 1: Set up the study
    console.print("\n" + "=" * 60)
    console.print("[bold]Step 1: Define Your Study[/bold]")
    console.print("=" * 60 + "\n")

    use_default = Confirm.ask(
        "Use default study (AI usage at work)?", default=True
    )

    if use_default:
        study = ResearchStudy(
            research_goals=[
                "Understand how professionals integrate AI tools into their daily work",
                "Identify pain points and satisfactions with current AI tools",
                "Explore concerns about AI's impact on their profession",
            ],
            target_population="Knowledge workers who use AI tools",
            hypotheses=[
                "Users feel tension between AI efficiency and maintaining their skills",
                "Trust in AI varies significantly by task type",
            ],
            duration_minutes=10,
            additional_context="Focus on practical, day-to-day experiences.",
        )
    else:
        # Custom study setup
        console.print("\n[bold]Define your research study:[/bold]\n")
        goals = []
        console.print("Enter research goals (empty line to finish):")
        while True:
            goal = Prompt.ask("  Goal", default="")
            if not goal:
                break
            goals.append(goal)

        if not goals:
            goals = ["Understand participant experiences"]

        population = Prompt.ask("Target population", default="General participants")
        duration = int(Prompt.ask("Target duration (minutes)", default="10"))

        study = ResearchStudy(
            research_goals=goals,
            target_population=population,
            duration_minutes=duration,
        )

    # Generate rubric
    console.print("\n[yellow]Generating interview rubric...[/yellow]")
    planner = PlanningAgent(client)
    rubric = planner.create_rubric(study)

    console.print(f"\n[green]✓ Created rubric: {rubric.study_title}[/green]")

    # Show the rubric
    if Confirm.ask("View the interview rubric?", default=True):
        console.print(Panel("Interview Rubric", style="bold blue"))
        for i, section in enumerate(rubric.sections, 1):
            console.print(f"\n[bold cyan]Section {i}: {section.get('name', 'Unnamed')}[/bold cyan]")
            console.print(f"[dim]{section.get('purpose', '')}[/dim]")
            for q in section.get("questions", []):
                console.print(f"  • {q.get('text', '')}")
                if q.get("probes"):
                    for probe in q["probes"][:2]:
                        console.print(f"    [dim]↳ {probe}[/dim]")

    # Save rubric
    config = StorageConfig(Path("./data"), "interactive_study")
    store = TranscriptStore(config)
    store.save_rubric(rubric.to_json())

    # Step 2: Participant context
    console.print("\n" + "=" * 60)
    console.print("[bold]Step 2: About You (Optional Context)[/bold]")
    console.print("=" * 60 + "\n")

    context = Prompt.ask(
        "Brief description of yourself for the interviewer",
        default="No specific context provided"
    )

    # Step 3: The Interview
    console.print("\n" + "=" * 60)
    console.print("[bold]Step 3: The Interview Begins[/bold]")
    console.print("=" * 60)
    console.print("[dim]Type 'quit' to end | 'state' to see progress[/dim]\n")

    interviewer = AdaptiveInterviewAgent(client)
    session = interviewer.start_session(
        rubric=rubric,
        participant_id="interactive_user",
        research_goal="; ".join(study.research_goals),
        participant_context=context,
        target_duration=study.duration_minutes,
    )

    # Display opening
    console.print(Panel(
        session.messages[-1].content,
        title="🎤 Interviewer",
        style="cyan",
    ))

    # Action display colors
    action_colors = {
        ProbeAction.PROBE_DEEPER: "bold red",
        ProbeAction.FOLLOW_UP: "bold yellow",
        ProbeAction.CLARIFY: "bold magenta",
        ProbeAction.REFLECT: "bold blue",
        ProbeAction.MOVE_ON: "bold green",
        ProbeAction.CIRCLE_BACK: "bold cyan",
        ProbeAction.REDIRECT: "bold white",
        ProbeAction.CLOSE: "bold white",
    }

    action_descriptions = {
        ProbeAction.PROBE_DEEPER: "Digging deeper into this topic",
        ProbeAction.FOLLOW_UP: "Following up on what you said",
        ProbeAction.CLARIFY: "Asking for clarification",
        ProbeAction.REFLECT: "Reflecting back your response",
        ProbeAction.MOVE_ON: "Moving to a new topic",
        ProbeAction.CIRCLE_BACK: "Circling back to earlier point",
        ProbeAction.REDIRECT: "Gently redirecting",
        ProbeAction.CLOSE: "Wrapping up the interview",
    }

    # Interview loop
    exchange_count = 0
    while not session.ended_at:
        console.print()
        response = Prompt.ask("[bold yellow]You[/bold yellow]")

        if response.lower() == "quit":
            session = interviewer.end_session(session)
            console.print(Panel(
                session.messages[-1].content,
                title="🎤 Interviewer",
                style="cyan",
            ))
            break

        if response.lower() == "state":
            state = interviewer.get_interview_state()
            if state:
                state_table = Table(title="Interview Progress", show_header=False)
                state_table.add_column("Metric", style="cyan")
                state_table.add_column("Value", style="green")
                for key, value in state.items():
                    state_table.add_row(key.replace("_", " ").title(), str(value))
                console.print(state_table)
            continue

        # Get adaptive response
        console.print("\n[dim]Analyzing your response...[/dim]")
        interviewer_response, decision = interviewer.respond(session, response)
        exchange_count += 1

        # Show the probing analysis
        console.print()
        action_color = action_colors.get(decision.action, "white")
        action_desc = action_descriptions.get(decision.action, decision.action.value)

        # Signals box
        if decision.signals_detected:
            signals_lines = []
            for s in decision.signals_detected[:4]:
                evidence = s.evidence[:50] + "..." if len(s.evidence) > 50 else s.evidence
                signals_lines.append(f"[bold]{s.signal_type.value.upper()}[/bold] ({s.confidence:.0%}): {evidence}")
            console.print(Panel(
                "\n".join(signals_lines),
                title="🔍 Signals Detected",
                style="dim",
                width=75,
            ))

        # Decision box
        console.print(Panel(
            f"[{action_color}]{decision.action.value.upper()}[/{action_color}]: {action_desc}\n"
            f"[dim]{decision.reasoning}[/dim]",
            title="🧠 Probe Decision",
            style="dim",
            width=75,
        ))

        # Progress bar
        state = interviewer.get_interview_state()
        if state:
            console.print(
                f"[dim]📊 Coverage: {state.get('coverage', '?')} | "
                f"Depth: {state.get('average_depth', '?')} | "
                f"Time: {state.get('time_elapsed', '?')} | "
                f"Remaining: {state.get('time_remaining', '?')}[/dim]"
            )

        # Show interviewer response
        console.print()
        console.print(Panel(
            interviewer_response,
            title="🎤 Interviewer",
            style="cyan",
        ))

        if session.ended_at:
            break

    # Save and summarize
    store.save_session(session)

    console.print("\n" + "=" * 60)
    console.print("[bold]Interview Complete![/bold]")
    console.print("=" * 60)

    # Final stats
    final_state = interviewer.get_interview_state()
    if final_state:
        state_table = Table(title="Final Statistics")
        state_table.add_column("Metric", style="cyan")
        state_table.add_column("Value", style="green")
        for key, value in final_state.items():
            state_table.add_row(key.replace("_", " ").title(), str(value))
        console.print(state_table)

    console.print(f"\n[green]Transcript saved to {config.transcripts_path}[/green]")
    console.print(f"[dim]Run 'python main.py analyze' to analyze this transcript[/dim]")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        console.print(
            """
[bold]Anthropic Interviewer[/bold] - AI-powered qualitative research

[bold]Commands:[/bold]
  [cyan]interactive[/cyan]  Be interviewed with live probing analysis (recommended!)
  plan         Create an interview rubric from research goals
  interview    Conduct a basic interview using a rubric
  analyze      Analyze collected transcripts for themes
  demo         Run a scripted demo workflow

[bold]Usage:[/bold]
  python main.py <command>

[bold]Try it:[/bold]
  python main.py interactive
"""
        )
        return

    command = sys.argv[1].lower()

    if command == "plan":
        create_rubric()
    elif command == "interview":
        conduct_interview()
    elif command == "analyze":
        analyze_transcripts()
    elif command == "demo":
        run_demo()
    elif command in ("interactive", "i"):
        run_interactive()
    else:
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print("Try: interactive, plan, interview, analyze, or demo")


if __name__ == "__main__":
    main()
