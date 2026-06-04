import "./globals.css";

export const metadata = {
  title: "SoloCinema",
  description: "Regina movie screenings sorted by inferred seat occupancy."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
