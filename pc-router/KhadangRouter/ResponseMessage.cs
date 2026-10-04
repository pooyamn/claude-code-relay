namespace KhadangRouter;

// Delivery belongs to a response, not to the native session. Keep this object
// alive across a rollover so a late send receipt cannot bind the next response
// to the previous response's Telegram message.
internal sealed class ResponseMessage
{
    public int? Message;
    public string LastRendered = "";
    public bool SendUnknown;
    public string Text = ""; // Frozen final text for an earlier response.
    public FinalAnswerState Answer = new();
}
