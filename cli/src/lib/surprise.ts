/**
 * Curated topic pool for the /surprise command.
 * Each category has an emoji, accent color, and list of fascinating topics.
 */

export interface SurpriseCategory {
  category: string;
  emoji: string;
  color: string;
  topics: string[];
}

export interface SurpriseChoice {
  category: string;
  emoji: string;
  color: string;
  topic: string;
}

export const SURPRISE_TOPICS: SurpriseCategory[] = [
  {
    category: 'Mathematics', emoji: '✦', color: '#FFD700',
    topics: [
      'Euler\'s identity — the most beautiful equation in math',
      'How the Mandelbrot set creates infinite fractal complexity',
      'The elegance of Fourier transforms — decomposing any signal into pure waves',
      'Why there are exactly 5 Platonic solids',
      'The Monty Hall problem — why switching doors wins',
      'How quaternions rotate 3D objects without gimbal lock',
      'The Banach-Tarski paradox — duplicating a sphere with pure math',
      'How eigenvectors reveal hidden structure in data',
      'The surprising geometry of the Fibonacci spiral in nature',
      'Gödel\'s incompleteness theorem — math\'s fundamental limitation',
    ],
  },
  {
    category: 'Physics', emoji: '⚛', color: '#64B4FF',
    topics: [
      'Quantum entanglement — spooky action at a distance',
      'How black holes warp spacetime into visual distortion',
      'The double-slit experiment — particles behaving like waves',
      'Why entropy always increases — the arrow of time',
      'How special relativity bends time and space',
      'The Coriolis effect — why hurricanes spin',
      'How Feynman diagrams visualize particle interactions',
      'Wave-particle duality — the heart of quantum mechanics',
      'How GPS satellites correct for relativistic time dilation',
      'The physics of soap bubbles — minimal surfaces in nature',
    ],
  },
  {
    category: 'Computer Science', emoji: '◈', color: '#00B4D8',
    topics: [
      'How RSA encryption keeps the internet secure',
      'The fast Fourier transform — the most important algorithm',
      'How neural networks learn to see — backpropagation visualized',
      'Dijkstra\'s algorithm — finding shortest paths in graphs',
      'How hash tables achieve O(1) lookups',
      'The halting problem — what computers can never solve',
      'How PageRank turned Google into a search giant',
      'Convex hull algorithms — gift wrapping geometry',
      'How transformers learn attention — the architecture behind LLMs',
      'The Byzantine generals problem — consensus in distributed systems',
    ],
  },
  {
    category: 'Biology', emoji: '❋', color: '#00C853',
    topics: [
      'How CRISPR edits DNA with molecular scissors',
      'The central dogma — DNA to RNA to protein',
      'How neurons fire and form neural networks in the brain',
      'The mathematics of population growth and carrying capacity',
      'How evolution works through natural selection — visualized',
      'The geometry of protein folding',
      'How the immune system recognizes and destroys invaders',
      'Cellular automata — Conway\'s Game of Life and emergent complexity',
    ],
  },
  {
    category: 'Engineering', emoji: '⬡', color: '#FF9800',
    topics: [
      'How a CPU executes instructions — the fetch-decode-execute cycle',
      'Control theory — how feedback loops stabilize systems',
      'How error-correcting codes protect data from corruption',
      'The math behind signal compression — how MP3 and JPEG work',
      'How PID controllers keep drones stable in the air',
      'The Nyquist-Shannon sampling theorem — digitizing the analog world',
    ],
  },
  {
    category: 'Visual Math', emoji: '◉', color: '#9C78FF',
    topics: [
      'Möbius strips and Klein bottles — surfaces with impossible geometry',
      'How the dot product measures similarity between vectors',
      'The beauty of complex number multiplication as rotation',
      'How matrix transformations deform space — linear algebra visualized',
      'Voronoi diagrams — nature\'s way of dividing space',
      'The surprising math of the Brachistochrone — the fastest slide',
      'How gradient descent finds the bottom of a loss landscape',
      'Bayes\' theorem — updating beliefs with evidence',
    ],
  },
];

export function pickSurprise(): SurpriseChoice {
  const pool = SURPRISE_TOPICS[Math.floor(Math.random() * SURPRISE_TOPICS.length)]!;
  const topic = pool.topics[Math.floor(Math.random() * pool.topics.length)]!;
  return { category: pool.category, emoji: pool.emoji, color: pool.color, topic };
}
