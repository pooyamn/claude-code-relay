using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;

namespace MediaProbe;

// Generated public pixels only. Truth stays in the protected diagnostic state,
// never in the model's text, filenames or PNG metadata.
public sealed record Fixture(byte[] Bytes, string[] Colors)
{
    public static Fixture Create()
    {
        var palette = new[] { ("red", 255, 0, 0), ("green", 0, 255, 0), ("blue", 0, 0, 255),
            ("yellow", 255, 255, 0), ("magenta", 255, 0, 255), ("cyan", 0, 255, 255) };
        for (int i = palette.Length - 1; i > 0; i--)
        {
            int j = RandomNumberGenerator.GetInt32(i + 1); (palette[i], palette[j]) = (palette[j], palette[i]);
        }
        using var pixels = new MemoryStream();
        for (int y = 0; y < 96; y++)
        {
            pixels.WriteByte(0); // PNG filter: none.
            for (int x = 0; x < 288; x++)
            {
                var color = palette[x / 96];
                pixels.WriteByte((byte)color.Item2); pixels.WriteByte((byte)color.Item3); pixels.WriteByte((byte)color.Item4);
            }
        }
        using var compressed = new MemoryStream();
        using (var z = new ZLibStream(compressed, CompressionLevel.SmallestSize, leaveOpen: true)) z.Write(pixels.ToArray());
        using var png = new MemoryStream(); png.Write(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 });
        var header = new byte[13]; BinaryPrimitives.WriteInt32BigEndian(header, 288);
        BinaryPrimitives.WriteInt32BigEndian(header.AsSpan(4), 96); header[8] = 8; header[9] = 2;
        Chunk(png, "IHDR"u8, header); Chunk(png, "IDAT"u8, compressed.ToArray()); Chunk(png, "IEND"u8, []);
        return new(png.ToArray(), palette.Take(3).Select(c => c.Item1).ToArray());
    }
    private static void Chunk(Stream target, ReadOnlySpan<byte> kind, byte[] bytes)
    {
        Span<byte> number = stackalloc byte[4]; BinaryPrimitives.WriteInt32BigEndian(number, bytes.Length);
        target.Write(number); target.Write(kind); target.Write(bytes);
        uint crc = uint.MaxValue;
        foreach (byte b in kind.ToArray().Concat(bytes))
        {
            crc ^= b;
            for (int bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ ((crc & 1) != 0 ? 0xedb88320u : 0);
        }
        BinaryPrimitives.WriteUInt32BigEndian(number, ~crc); target.Write(number);
    }
}
