import React, { useState } from 'react';
import { Spinner, Form, Button } from 'react-bootstrap';

function Search({ onSearchTextTrigger}) {
    const [query, setQuery] = useState('');
    // const [results, setResults] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');

    const handleSearch = async (e) => {
        e.preventDefault();
        setError('');
        setIsLoading(true);
        try {
            console.log('Query Received: ', query);
            onSearchTextTrigger(query);
        } catch (error) {
            console.error('Search failed:', error);
            setError('Search failed. Please try again.');
        }
        setIsLoading(false);
    };

    return (
        <div className="mt-3">
            <Form onSubmit={handleSearch}>
                <Form.Group className="mb-3" controlId="searchQuery">
                    <Form.Control
                        type="text"
                        value={query}
                        onChange={e => setQuery(e.target.value)}
                        placeholder="Search songs"
                        required
                    />
                </Form.Group>
                <Button variant="primary" type="submit" disabled={isLoading}>
                    {isLoading ? <Spinner as="span" animation="border" size="sm" role="status" aria-hidden="true" /> : "Search"}
                </Button>
            </Form>
            {error && <div className="text-danger">{error}</div>}   
            {/* <ListGroup className="mt-3">
                {results.map(song => (
                    <ListGroup.Item key={song.id}>
                        {song.title} by {song.artist}
                    </ListGroup.Item>
                ))}
            </ListGroup> */}
        </div>
    );
}

export default Search;
