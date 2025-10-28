import Image from 'next/image';

export default function Home() {
  return (
    <main className="flex flex-col items-center justify-center min-h-screen bg-gradient-to-br from-[#0b1830] via-[#12264a] to-[#0b1830] text-white">
      <Image src="/ReChargeLogo_REVA.png" alt="ReCharge Logo" width={220} height={220} />
      <h1 className="mt-6 text-3xl font-semibold">Welcome to ReCharge Alaska Portal</h1>
      <div className="mt-8 flex space-x-6">
        <a
          href="/login"
          className="px-6 py-3 rounded-full bg-[#3ab54a] text-white font-semibold transition hover:brightness-110"
        >
          Login
        </a>
        <a
          href="/app"
          className="px-6 py-3 rounded-full border-2 border-[#0b1830] text-[#3ab54a] font-semibold bg-transparent transition hover:brightness-110"
        >
          Dashboard
        </a>
      </div>
    </main>
  );
}