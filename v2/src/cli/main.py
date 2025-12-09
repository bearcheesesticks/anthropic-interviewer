"""CLI for Anthropic Interviewer.

Usage:
    interviewer study create "My Study" --goals "Goal 1" --goals "Goal 2"
    interviewer rubric generate 1
    interviewer interview start 1 --participant "P001"
    interviewer analyze study 1
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from pathlib import Path

from src.db.session import init_db, get_db
from src.db.models import StudyStatus

app = typer.Typer(
    name="interviewer",
    help="AI-powered qualitative research interviews",
    no_args_is_help=True,
)
console = Console()

# Sub-commands
study_app = typer.Typer(help="Manage research studies")
rubric_app = typer.Typer(help="Manage interview rubrics")
interview_app = typer.Typer(help="Conduct interviews")
analyze_app = typer.Typer(help="Analyze transcripts")

app.add_typer(study_app, name="study")
app.add_typer(rubric_app, name="rubric")
app.add_typer(interview_app, name="interview")
app.add_typer(analyze_app, name="analyze")


def get_services():
    """Get service instances with database session."""
    from anthropic import Anthropic
    from src.services import PlanningService, InterviewService, AnalysisService

    db = next(get_db())
    client = Anthropic()

    return {
        "db": db,
        "planning": PlanningService(db, client),
        "interview": InterviewService(db, client),
        "analysis": AnalysisService(db, client),
    }


# =============================================================================
# Study Commands
# =============================================================================


@study_app.command("create")
def study_create(
    name: str = typer.Argument(..., help="Study name"),
    goals: list[str] = typer.Option([], "--goal", "-g", help="Research goals"),
    population: str = typer.Option("", "--population", "-p", help="Target population"),
    duration: int = typer.Option(15, "--duration", "-d", help="Target duration in minutes"),
):
    """Create a new research study."""
    init_db()
    services = get_services()

    from src.core.models import StudyConfig

    # Interactive mode if no goals provided
    if not goals:
        console.print(Panel("Create New Study", style="bold blue"))
        console.print("\nEnter research goals (empty line to finish):")
        goals = []
        while True:
            goal = Prompt.ask("  Goal", default="")
            if not goal:
                break
            goals.append(goal)

        if not goals:
            console.print("[red]At least one research goal required.[/red]")
            raise typer.Exit(1)

        if not population:
            population = Prompt.ask("Target population")

    config = StudyConfig(
        name=name,
        research_goals=goals,
        target_population=population,
        target_duration_minutes=duration,
    )

    study = services["planning"].create_study(config)

    console.print(f"\n[green]✓ Created study:[/green] {study.name} (ID: {study.id})")
    console.print(f"  Goals: {len(study.research_goals)}")
    console.print(f"  Duration: {study.target_duration_minutes} min")
    console.print(f"\n[dim]Next: Run 'interviewer rubric generate {study.id}' to create interview rubric[/dim]")


@study_app.command("list")
def study_list():
    """List all studies."""
    init_db()
    services = get_services()

    studies = services["planning"].list_studies()

    if not studies:
        console.print("[dim]No studies found. Create one with 'interviewer study create'[/dim]")
        return

    table = Table(title="Studies")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Goals")
    table.add_column("Interviews")

    for s in studies:
        interview_count = len(s.interviews)
        table.add_row(
            str(s.id),
            s.name,
            s.status.value,
            str(len(s.research_goals)),
            str(interview_count),
        )

    console.print(table)


@study_app.command("show")
def study_show(study_id: int = typer.Argument(..., help="Study ID")):
    """Show study details."""
    init_db()
    services = get_services()

    study = services["planning"].get_study(study_id)
    if not study:
        console.print(f"[red]Study {study_id} not found[/red]")
        raise typer.Exit(1)

    console.print(Panel(f"Study: {study.name}", style="bold blue"))
    console.print(f"\n[bold]Status:[/bold] {study.status.value}")
    console.print(f"[bold]Duration:[/bold] {study.target_duration_minutes} min")
    console.print(f"[bold]Population:[/bold] {study.target_population}")

    console.print(f"\n[bold]Research Goals:[/bold]")
    for i, goal in enumerate(study.research_goals, 1):
        console.print(f"  {i}. {goal}")

    if study.hypotheses:
        console.print(f"\n[bold]Hypotheses:[/bold]")
        for h in study.hypotheses:
            console.print(f"  - {h}")

    console.print(f"\n[bold]Rubrics:[/bold] {len(study.rubrics)}")
    console.print(f"[bold]Interviews:[/bold] {len(study.interviews)}")


# =============================================================================
# Rubric Commands
# =============================================================================


@rubric_app.command("generate")
def rubric_generate(study_id: int = typer.Argument(..., help="Study ID")):
    """Generate an interview rubric for a study."""
    init_db()
    services = get_services()

    study = services["planning"].get_study(study_id)
    if not study:
        console.print(f"[red]Study {study_id} not found[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Generating rubric for '{study.name}'...[/yellow]")

    rubric_data = services["planning"].generate_rubric(study)
    rubric = services["planning"].save_rubric(study, rubric_data)

    console.print(f"\n[green]✓ Generated rubric:[/green] {rubric.title} (v{rubric.version})")

    # Show rubric
    console.print(Panel("Interview Rubric", style="bold blue"))
    for section in rubric.sections:
        console.print(f"\n[bold cyan]{section.name}[/bold cyan]")
        if section.purpose:
            console.print(f"[dim]{section.purpose}[/dim]")
        for q in section.questions:
            console.print(f"  • [{q.question_id}] {q.text}")

    console.print(f"\n[dim]Review and approve with: interviewer rubric approve {rubric.id}[/dim]")


@rubric_app.command("approve")
def rubric_approve(rubric_id: int = typer.Argument(..., help="Rubric ID")):
    """Approve a rubric for use in interviews."""
    init_db()
    services = get_services()

    rubric = services["planning"].approve_rubric(rubric_id)
    console.print(f"[green]✓ Approved rubric {rubric_id} for study '{rubric.study.name}'[/green]")
    console.print(f"\n[dim]Start interviews with: interviewer interview start {rubric.study_id}[/dim]")


@rubric_app.command("show")
def rubric_show(rubric_id: int = typer.Argument(..., help="Rubric ID")):
    """Show rubric details."""
    init_db()
    services = get_services()

    rubric = services["planning"].get_rubric(rubric_id)
    if not rubric:
        console.print(f"[red]Rubric {rubric_id} not found[/red]")
        raise typer.Exit(1)

    console.print(Panel(f"Rubric: {rubric.title} (v{rubric.version})", style="bold blue"))
    console.print(f"[bold]Active:[/bold] {'Yes' if rubric.is_active else 'No'}")
    console.print(f"[bold]Approved:[/bold] {'Yes' if rubric.is_approved else 'No'}")

    for section in rubric.sections:
        console.print(f"\n[bold cyan]{section.name}[/bold cyan]")
        if section.purpose:
            console.print(f"[dim]{section.purpose}[/dim]")
        for q in section.questions:
            console.print(f"  • [{q.question_id}] {q.text}")
            if q.probes:
                for probe in q.probes[:2]:
                    console.print(f"    [dim]↳ {probe}[/dim]")


# =============================================================================
# Interview Commands
# =============================================================================


@interview_app.command("start")
def interview_start(
    study_id: int = typer.Argument(..., help="Study ID"),
    participant: str = typer.Option("", "--participant", "-p", help="Participant ID"),
    context: str = typer.Option("", "--context", "-c", help="Participant context"),
    show_analysis: bool = typer.Option(False, "--show-analysis", "-a", help="Show probing analysis"),
):
    """Start an interactive interview session."""
    init_db()
    services = get_services()

    study = services["planning"].get_study(study_id)
    if not study:
        console.print(f"[red]Study {study_id} not found[/red]")
        raise typer.Exit(1)

    # Check for active rubric
    rubric = services["planning"].get_active_rubric(study_id)
    if not rubric:
        console.print(f"[red]No active rubric for study. Generate and approve one first.[/red]")
        raise typer.Exit(1)

    # Get participant info if not provided
    if not participant:
        participant = Prompt.ask("Participant ID")
    if not context:
        context = Prompt.ask("Participant context (optional)", default="")

    from src.core.models import InterviewConfig

    config = InterviewConfig(
        participant_id=participant,
        participant_context=context,
        show_probing_analysis=show_analysis,
    )

    console.print(f"\n[yellow]Starting interview...[/yellow]")

    interview, opening = services["interview"].start_interview(study, config)

    console.print(Panel("Interview Started", style="bold green"))
    console.print("[dim]Type 'quit' to end | 'state' for progress[/dim]\n")

    # Show opening
    console.print(Panel(opening, title="🎤 Interviewer", style="cyan"))

    # Interview loop
    while interview.status.value == "in_progress":
        console.print()
        response = Prompt.ask("[bold yellow]You[/bold yellow]")

        if response.lower() == "quit":
            closing = services["interview"].end_interview(interview)
            console.print(Panel(closing, title="🎤 Interviewer", style="cyan"))
            break

        if response.lower() == "state":
            state = services["interview"].get_interview_state(interview)
            _show_interview_state(state)
            continue

        console.print("\n[dim]Processing...[/dim]")
        interviewer_response, decision = services["interview"].process_response(
            interview, response
        )

        # Show analysis if enabled
        if show_analysis:
            _show_probe_decision(decision)

        console.print(Panel(interviewer_response, title="🎤 Interviewer", style="cyan"))

        # Refresh interview from DB
        services["db"].refresh(interview)

    # Final stats
    console.print("\n" + "=" * 60)
    console.print("[bold]Interview Complete[/bold]")
    state = services["interview"].get_interview_state(interview)
    _show_interview_state(state)


@interview_app.command("list")
def interview_list(study_id: int = typer.Argument(..., help="Study ID")):
    """List all interviews for a study."""
    init_db()
    services = get_services()

    interviews = services["interview"].list_interviews(study_id)

    if not interviews:
        console.print("[dim]No interviews found.[/dim]")
        return

    table = Table(title="Interviews")
    table.add_column("ID", style="cyan")
    table.add_column("Participant")
    table.add_column("Status")
    table.add_column("Messages")
    table.add_column("Duration")

    for i in interviews:
        duration = f"{i.duration_minutes:.1f} min" if i.duration_minutes else "-"
        table.add_row(
            str(i.id),
            i.participant_id,
            i.status.value,
            str(len(i.messages)),
            duration,
        )

    console.print(table)


@interview_app.command("transcript")
def interview_transcript(interview_id: int = typer.Argument(..., help="Interview ID")):
    """Show interview transcript."""
    init_db()
    services = get_services()

    interview = services["interview"].get_interview(interview_id)
    if not interview:
        console.print(f"[red]Interview {interview_id} not found[/red]")
        raise typer.Exit(1)

    console.print(Panel(f"Transcript: Interview {interview_id}", style="bold blue"))
    console.print(f"Participant: {interview.participant_id}")
    console.print(f"Status: {interview.status.value}\n")

    console.print(interview.transcript)


# =============================================================================
# Analysis Commands
# =============================================================================


@analyze_app.command("transcript")
def analyze_transcript(interview_id: int = typer.Argument(..., help="Interview ID")):
    """Analyze a single interview transcript."""
    init_db()
    services = get_services()

    interview = services["interview"].get_interview(interview_id)
    if not interview:
        console.print(f"[red]Interview {interview_id} not found[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Analyzing transcript...[/yellow]")

    analysis = services["analysis"].analyze_transcript(interview)
    services["analysis"].save_analysis(analysis)

    console.print(Panel("Analysis Complete", style="bold green"))
    console.print(f"\n[bold]Summary:[/bold] {analysis.summary}")

    console.print(f"\n[bold]Codes ({len(analysis.codes)}):[/bold]")
    for code in analysis.codes[:10]:
        console.print(f"  • {code.code_name}: \"{code.quotation[:60]}...\"")

    if analysis.notable_insights:
        console.print(f"\n[bold]Notable Insights:[/bold]")
        for insight in analysis.notable_insights:
            console.print(f"  - {insight}")


@analyze_app.command("study")
def analyze_study(study_id: int = typer.Argument(..., help="Study ID")):
    """Analyze all transcripts and synthesize themes."""
    init_db()
    services = get_services()

    study = services["planning"].get_study(study_id)
    if not study:
        console.print(f"[red]Study {study_id} not found[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Analyzing all transcripts for '{study.name}'...[/yellow]")

    # Analyze individual transcripts
    analyses = services["analysis"].analyze_all_transcripts(study)
    console.print(f"[green]✓ Analyzed {len(analyses)} transcripts[/green]")

    # Synthesize themes
    console.print(f"\n[yellow]Synthesizing themes...[/yellow]")
    synthesis = services["analysis"].synthesize_themes(study)
    services["analysis"].save_theme_synthesis(study, synthesis)

    console.print(Panel("Theme Synthesis Complete", style="bold green"))

    console.print(f"\n[bold]Themes ({len(synthesis.themes)}):[/bold]")
    for theme in synthesis.themes:
        console.print(f"\n  [cyan]{theme.name}[/cyan]")
        console.print(f"  {theme.description}")

    if synthesis.research_findings:
        console.print(f"\n[bold]Research Findings:[/bold]")
        for finding in synthesis.research_findings:
            console.print(f"\n  [bold]{finding.get('question', 'RQ')}[/bold]")
            console.print(f"  {finding.get('finding', '')}")

    if synthesis.unexpected_discoveries:
        console.print(f"\n[bold]Unexpected Discoveries:[/bold]")
        for d in synthesis.unexpected_discoveries:
            console.print(f"  - {d}")


# =============================================================================
# Helpers
# =============================================================================


def _show_probe_decision(decision):
    """Display probe decision analysis."""
    from src.core.models import ProbeAction

    action_colors = {
        ProbeAction.PROBE_DEEPER: "red",
        ProbeAction.FOLLOW_UP: "yellow",
        ProbeAction.CLARIFY: "magenta",
        ProbeAction.REFLECT: "blue",
        ProbeAction.MOVE_ON: "green",
        ProbeAction.CIRCLE_BACK: "cyan",
        ProbeAction.REDIRECT: "white",
        ProbeAction.CLOSE: "white",
    }

    color = action_colors.get(decision.action, "white")

    if decision.signals:
        signals_text = "\n".join(
            f"  {s.signal_type.value.upper()}: {s.evidence[:50]}..."
            for s in decision.signals[:3]
        )
        console.print(Panel(signals_text, title="🔍 Signals", style="dim", width=70))

    console.print(Panel(
        f"[{color}]{decision.action.value.upper()}[/{color}]\n[dim]{decision.reasoning}[/dim]",
        title="🧠 Decision",
        style="dim",
        width=70,
    ))


def _show_interview_state(state):
    """Display interview state."""
    table = Table(title="Interview Progress", show_header=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Messages", str(state.message_count))
    if state.coverage is not None:
        table.add_row("Coverage", f"{state.coverage * 100:.0f}%")
    if state.average_depth is not None:
        table.add_row("Avg Depth", f"{state.average_depth:.1f}/3")
    if state.time_remaining is not None:
        table.add_row("Time Left", f"{state.time_remaining:.1f} min")
    if state.duration_minutes:
        table.add_row("Duration", f"{state.duration_minutes:.1f} min")

    console.print(table)


# =============================================================================
# Init Command
# =============================================================================


@app.command("init")
def init_database(
    path: Path = typer.Option(
        Path("./data/interviewer.db"),
        "--path", "-p",
        help="Database path"
    )
):
    """Initialize the database."""
    init_db(path)
    console.print(f"[green]✓ Database initialized at {path}[/green]")


if __name__ == "__main__":
    app()
