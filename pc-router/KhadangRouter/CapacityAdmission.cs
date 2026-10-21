namespace KhadangRouter;

// A known pre-dispatch resource refusal, never an uncertain native action.
public sealed class CapacityDenied(int maximum) : Exception("Active session capacity reached")
{
    public int Maximum { get; } = maximum;
}
